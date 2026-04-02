from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders.recursive_url_loader import RecursiveUrlLoader
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from uuid import uuid4
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

CHROMA_PATH = r"chroma_db"

# Render instances can be small (e.g., 512MB). Website ingestion is the spikiest
# memory path, so we hard-cap how much we crawl/chunk per request.
MAX_PAGES_PER_INGEST = int(os.getenv("MAX_PAGES_PER_INGEST", "40"))
MAX_PAGE_CHARS = int(os.getenv("MAX_PAGE_CHARS", "25000"))          # per page (post-extraction)
MAX_TOTAL_CHARS = int(os.getenv("MAX_TOTAL_CHARS", "400000"))       # across all pages
MAX_CHUNKS_PER_INGEST = int(os.getenv("MAX_CHUNKS_PER_INGEST", "400"))
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "48"))

def normalize_url(url: str) -> str:
    """Normalize a URL for consistent matching (removes trailing slash and www.)."""
    url = url.strip()
    if url.endswith("/"):
        url = url[:-1]
    url = url.replace("https://www.", "https://")
    url = url.replace("http://www.", "http://")
    return url

def _seed_urls(url: str) -> list[str]:
    """
    Return up to 2 seed URLs: `example.com` and `www.example.com`.

    `RecursiveUrlLoader(prevent_outside=True)` blocks links when the netloc
    changes (e.g., `www` vs non-`www`), so we crawl both variants to improve
    coverage.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    hostname = parsed.hostname or ""
    # If the input was missing scheme, urlparse("example.com") puts it in path.
    if not hostname:
        parsed = urlparse(f"https://{url}")
        scheme = parsed.scheme
        hostname = parsed.hostname or ""

    hostname = hostname.strip()
    if hostname.startswith("www."):
        base_host = hostname[len("www.") :]
    else:
        base_host = hostname

    # Keep the original path if caller passed one; widget typically passes `/`.
    path = parsed.path or "/"
    path = path if path.startswith("/") else f"/{path}"

    candidates = [f"{scheme}://{base_host}{path}"]
    candidates.append(f"{scheme}://www.{base_host}{path}")

    # De-dupe while preserving order
    out: list[str] = []
    for c in candidates:
        c_norm = c.rstrip("/")
        if c_norm not in out:
            out.append(c_norm)
    return out

# Initiate the models
embeddings_model = OpenAIEmbeddings(model="text-embedding-3-large")
llm = ChatOpenAI(temperature=0.5, model='gpt-4o-mini')

# Connect to the chromadb
vector_store = Chroma(
    collection_name="example_collection",
    embedding_function=embeddings_model,
    persist_directory=CHROMA_PATH, 
)

def extract_text_from_html(html: str) -> str:
    """Helper to extract clean text from HTML"""
    soup = BeautifulSoup(html, "lxml")
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.extract()
    text = soup.get_text(separator=' ')
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = '\n'.join(chunk for chunk in chunks if chunk)
    return text

def _iter_loader_docs(loader: RecursiveUrlLoader, *, max_pages: int) -> list:
    """
    Use lazy loading to avoid materializing an entire crawl in memory.
    Stops after `max_pages` documents.
    """
    out = []
    for doc in loader.lazy_load():
        out.append(doc)
        if len(out) >= max_pages:
            break
    return out

def _safe_trim_documents(documents: list) -> list:
    """Trim overly-large pages to avoid memory blowups."""
    total = 0
    trimmed = []
    for doc in documents:
        if not getattr(doc, "page_content", ""):
            continue
        content = doc.page_content.strip()
        if not content:
            continue
        if len(content) > MAX_PAGE_CHARS:
            content = content[:MAX_PAGE_CHARS]
            doc.page_content = content
        if total + len(content) > MAX_TOTAL_CHARS:
            break
        total += len(content)
        trimmed.append(doc)
    return trimmed

def _delete_existing_for_website(website_url: str) -> None:
    """Prevent unbounded DB growth for the same website."""
    try:
        vector_store._collection.delete(where={"website_url": website_url})
    except Exception:
        # If delete-by-filter isn't supported in the current Chroma setup, skip.
        pass

def ingest_website(url: str, max_depth: int = 2):
    """
    Crawls a website starting at the given URL up to max_depth.
    Extracts text, chunks it, and adds it to the vector store with the URL as metadata.
    """
    try:
        normalized_url = normalize_url(url)

        default_headers = {
            # Helps some sites that block "unknown" default clients.
            "User-Agent": "Mozilla/5.0 (support-agent; chatbot ingestion)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        # Crawl both www and non-www variants to avoid `prevent_outside` netloc mismatch.
        documents = []
        for seed_url in _seed_urls(url):
            loader = RecursiveUrlLoader(
                url=seed_url,
                max_depth=max_depth,
                extractor=extract_text_from_html,
                prevent_outside=True,
                timeout=30,
                continue_on_failure=True,
                headers=default_headers,
                check_response_status=False,
            )
            documents = _iter_loader_docs(loader, max_pages=MAX_PAGES_PER_INGEST)
            if documents:
                break

        if not documents:
            return {"status": "error", "message": f"No content found at {url}"}

        # De-dupe by the loader's `source` (helps with redirects/canonical URLs).
        seen_sources = set()
        unique_documents = []
        for doc in documents:
            source = doc.metadata.get("source")
            if source in seen_sources:
                continue
            seen_sources.add(source)
            unique_documents.append(doc)
        documents = unique_documents
        documents = _safe_trim_documents(documents)

        if not documents:
            return {"status": "error", "message": f"No usable text content found at {url}"}

        # Add a common "website_url" metadata attribute for filtering.
        # We intentionally store the *normalized* input URL so widget requests match.
        for doc in documents:
            doc.metadata["website_url"] = normalized_url
            
        # Split into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=150,
        )
        chunks = text_splitter.split_documents(documents)
        if len(chunks) > MAX_CHUNKS_PER_INGEST:
            chunks = chunks[:MAX_CHUNKS_PER_INGEST]
        
        # Replace previous ingestion for this site to control memory/disk growth.
        _delete_existing_for_website(normalized_url)

        # Add to vector store in batches to avoid big in-memory embedding calls.
        added = 0
        for i in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[i : i + EMBED_BATCH_SIZE]
            uuids = [str(uuid4()) for _ in range(len(batch))]
            vector_store.add_documents(documents=batch, ids=uuids)
            added += len(batch)
        
        return {
            "status": "success",
            "message": (
                f"Successfully added {added} chunks from {url} "
                f"(normalized: {normalized_url}, pages: {len(documents)})"
            ),
        }
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}

def stream_chat_response(url: str, message: str, history: list):
    """
    Retrieves context for a given website and streams the LLM response.
    """
    # Create a retriever that filters specifically for the website url
    normalized_url = normalize_url(url)
    retriever = vector_store.as_retriever(
        search_kwargs={
            'k': 5,
            'filter': {"website_url": normalized_url}
        }
    )
    
    docs = retriever.invoke(message)
    knowledge = "".join((doc.page_content + "\n\n") for doc in docs)

    if not knowledge.strip():
        # Avoid calling the LLM with empty context; it tends to guess.
        yield (
            "Sorry, I don't have enough information from that website yet. "
            "Please ingest the site in the admin dashboard first, or contact the website's support directly."
        )
        return

    rag_prompt = f"""
You are a helpful customer support agent for the website: {url}.
Answer the user's questions based strictly on the provided knowledge.
Do not use your internal knowledge, but solely the information in the "The knowledge" section.
If the answer is not in the knowledge, politely say that you don't know and offer the user to contact the website's support directly.
Do not tell the user that you are reading from a knowledge base.
Be friendly and concise in your responses.

The question: {message}

Conversation history: {history}

The knowledge: {knowledge}
"""

    # We use a generator to yield content for the StreamingResponse
    for response in llm.stream(rag_prompt):
        yield response.content
