from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders.recursive_url_loader import RecursiveUrlLoader
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from uuid import uuid4
import os

from dotenv import load_dotenv
load_dotenv()

CHROMA_PATH = r"chroma_db"

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

def ingest_website(url: str, max_depth: int = 2):
    """
    Crawls a website starting at the given URL up to max_depth.
    Extracts text, chunks it, and adds it to the vector store with the URL as metadata.
    """
    try:
        # Load the website
        loader = RecursiveUrlLoader(
            url=url,
            max_depth=max_depth,
            extractor=extract_text_from_html,
            prevent_outside=True
        )
        documents = loader.load()
        
        if not documents:
            return {"status": "error", "message": f"No content found at {url}"}
            
        # Add a common "website_url" metadata attribute for filtering
        for doc in documents:
            doc.metadata["website_url"] = url
            
        # Split into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=150,
        )
        chunks = text_splitter.split_documents(documents)
        
        # Add to vector store
        uuids = [str(uuid4()) for _ in range(len(chunks))]
        vector_store.add_documents(documents=chunks, ids=uuids)
        
        return {"status": "success", "message": f"Successfully added {len(chunks)} chunks from {url}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def stream_chat_response(url: str, message: str, history: list):
    """
    Retrieves context for a given website and streams the LLM response.
    """
    # Create a retriever that filters specifically for the website url
    retriever = vector_store.as_retriever(
        search_kwargs={
            'k': 5,
            'filter': {"website_url": url}
        }
    )
    
    docs = retriever.invoke(message)
    knowledge = ""
    for doc in docs:
        knowledge += doc.page_content + "\n\n"

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
