"""Test if prompt linking is working in Langfuse traces."""

import time

from dotenv import load_dotenv
from langfuse import Langfuse

load_dotenv()

client = Langfuse()

# Get the prompt
prompt = client.get_prompt("summarize-document", type="chat")
print(f"✓ Fetched prompt: {prompt.name} v{prompt.version}")
print(f"  Type: {type(prompt).__name__}")

# Create a test trace with prompt linking
print("\n✓ Creating test trace with prompt linking...")
with client.start_as_current_observation(
    as_type="generation",
    name="test-prompt-linking",
    model="test-model",
    prompt=prompt,  # Link the prompt here
    input={"test": "input"},
) as generation:
    print(f"  Generation created: {generation}")

    # Update with output
    generation.update(
        output={"test": "output"},
        metadata={"test": True},
    )

# Flush to ensure data is sent
print("\n✓ Flushing to Langfuse...")
client.flush()

# Give it a moment to process
time.sleep(2)

print("\n✓ Done! Check Langfuse UI for a trace named 'test-prompt-linking'")
print("  The generation should show a link to 'summarize-document' prompt v1")
