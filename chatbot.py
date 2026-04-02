import gradio as gr
from agent_service import ingest_website
import time

def process_url(url, depth):
    if not url:
        return "✗ Please enter a valid URL."
    
    yield "⏳ Crawling and ingesting website... This may take a moment."
    
    # Run the ingestion
    result = ingest_website(url, int(depth))
    
    if result["status"] == "success":
        yield f"✅ {result['message']}\n\nTo test this, embed the widget on {url} or a local test page mimicking that origin."
    else:
        yield f"❌ Error: {result['message']}"

with gr.Blocks(title="Admin Dashboard - Website Agent") as demo:
    gr.Markdown("# 🚀 Website Agent Admin Dashboard")
    gr.Markdown("Use this dashboard to crawl a website and add its content to the agent's knowledge base. Once ingested, the widget installed on that website will be able to answer questions based on the content.")
    
    with gr.Row():
        with gr.Column(scale=1):
            url_input = gr.Textbox(label="Website URL", placeholder="https://example.com")
            depth_input = gr.Slider(minimum=1, maximum=5, step=1, value=2, label="Crawl Depth")
            submit_btn = gr.Button("Ingest Website", variant="primary")
            status_output = gr.Textbox(label="Status", interactive=False, lines=4)
        
        with gr.Column(scale=1):
            gr.Markdown("### 🧑‍💻 How to Install on Website")
            gr.Code(
                value='<!-- Paste this right before the closing </body> tag -->\n<script src="http://localhost:8000/widget.js"></script>',
                language="html",
                interactive=False
            )
            gr.Markdown("> **Note:** Change `http://localhost:8000` to your actual server domain in production.")

    submit_btn.click(
        fn=process_url,
        inputs=[url_input, depth_input],
        outputs=status_output,
    )

if __name__ == "__main__":
    demo.launch()