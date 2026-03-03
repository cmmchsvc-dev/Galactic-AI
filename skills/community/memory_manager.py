"""
Galactic AI -- MemoryManager Skill
Provides long-term memory capabilities using a vector database (ChromaDB).
"""

import asyncio
from skills.base import GalacticSkill

try:
    import chromadb
    from chromadb.utils import embedding_functions
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

class MemoryManagerSkill(GalacticSkill):
    """
    Manages the AI's long-term memory using ChromaDB for semantic search.
    """
    skill_name  = "memory_manager"
    version     = "1.0.0"
    author      = "Galactic AI"
    description = "Vector database long-term memory using ChromaDB."
    category    = "data"
    icon        = "\U0001f4be"

    def __init__(self, core):
        super().__init__(core)
        self.client = None
        self.collection = None
        # Use a sentence transformer model appropriate for a local setup
        self.embed_fn = None

    async def on_load(self):
        """Initialize the ChromaDB client and collection asynchronously."""
        if not CHROMA_AVAILABLE:
            await self.core.log("[Memory] ChromaDB library not found. Run: pip install chromadb", priority=1)
            return

        def _init_chroma():
            """Blocking ChromaDB initialization."""
            try:
                # Path for persistent storage
                chroma_path = self.core.config.get('paths', {}).get('chroma_data', 'chroma_data')
                
                # Initialize client and embedding function
                self.client = chromadb.PersistentClient(path=chroma_path)
                self.embed_fn = embedding_functions.DefaultEmbeddingFunction()

                # Get or create the main collection for memories
                self.collection = self.client.get_or_create_collection(
                    name="long_term_memory",
                    embedding_function=self.embed_fn
                )
                return "[Memory] ChromaDB client initialized successfully."
            except Exception as e:
                return f"[Memory] Error initializing ChromaDB: {e}"

        # Run the blocking init in a separate thread
        init_message = await asyncio.to_thread(_init_chroma)
        await self.core.log(init_message, priority=2)

    def get_tools(self):
        if not CHROMA_AVAILABLE:
            return {}
        return {
            "store_memory": {
                "description": "Store a piece of text (a fact, a user preference, a plan step) in long-term vector memory for future recall.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text content to store in memory."},
                        "metadata": {"type": "object", "description": "Optional metadata (e.g., source, type, timestamp)."}
                    },
                    "required": ["text"]
                },
                "fn": self.store_memory
            },
            "recall_memories": {
                "description": "Recall relevant memories from the vector database based on a semantic query. Useful for finding context before answering a question.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The question or topic to search for in memory."},
                        "n_results": {"type": "integer", "description": "The number of results to return (default: 3)."}
                    },
                    "required": ["query"]
                },
                "fn": self.recall_memories
            }
        }

    async def store_memory(self, args):
        """Tool handler for storing a memory."""
        if not self.collection:
            return "[ERROR] Memory collection is not available."

        text = args.get('text')
        metadata = args.get('metadata', {})
        
        # ChromaDB requires string values for metadata
        for key, value in metadata.items():
            metadata[key] = str(value)

        def _add_to_collection():
            """Blocking call to add to Chroma."""
            try:
                # Use hash of the text as a unique ID to avoid duplicates
                import hashlib
                doc_id = hashlib.sha256(text.encode()).hexdigest()
                self.collection.add(
                    documents=[text],
                    metadatas=[metadata],
                    ids=[doc_id]
                )
                return f"[Memory] Stored: '{text[:50]}...'"
            except Exception as e:
                return f"[ERROR] Failed to store memory: {e}"
        
        return await asyncio.to_thread(_add_to_collection)

    async def recall_memories(self, args):
        """Tool handler for recalling memories."""
        if not self.collection:
            return "[ERROR] Memory collection is not available."

        query = args.get('query')
        n_results = args.get('n_results', 3)

        def _query_collection():
            """Blocking call to query Chroma."""
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=n_results
                )
                
                if not results or not results.get('documents') or not results['documents'][0]:
                    return "[Memory] No relevant memories found."

                # Format the results for the AI
                output = ["[Memory] Recalled Memories:"]
                for i, doc in enumerate(results['documents'][0]):
                    output.append(f"  {i+1}. {doc}")
                return "\\n".join(output)
            except Exception as e:
                return f"[ERROR] Failed to recall memories: {e}"

        return await asyncio.to_thread(_query_collection)
