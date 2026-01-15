"""Check Langfuse prompt object attributes for linking."""

from dotenv import load_dotenv
from langfuse import Langfuse

load_dotenv()

client = Langfuse()

# Get the prompt
prompt = client.get_prompt("summarize-document", type="chat")

# Check what attributes the prompt object has
print("Prompt attributes:")
for attr in dir(prompt):
    if not attr.startswith("_"):
        try:
            value = getattr(prompt, attr)
            if not callable(value):
                print(f"  {attr}: {value}")
        except Exception:
            pass

# Check specifically for linking attributes
print("\nKey linking attributes:")
print(f"  name: {getattr(prompt, 'name', None)}")
print(f"  version: {getattr(prompt, 'version', None)}")
print(f"  id: {getattr(prompt, 'id', None)}")
print(f"  type: {getattr(prompt, 'type', None)}")
