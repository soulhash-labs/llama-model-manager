"""
Ollama Client
=============
Local Ollama integration for private AI inference.
"""

from typing import Optional, Dict, Any


class OllamaClient:
    """Ollama client for local AI inference."""
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3:70b",
        timeout: int = 30,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._available = False
        
        # Check availability
        self._check_availability()
    
    def _check_availability(self):
        """Check if Ollama is available."""
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            self._available = response.status_code == 200
        except Exception:
            self._available = False
    
    def is_available(self) -> bool:
        """Check if Ollama is running."""
        return self._available
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate response from prompt.
        
        Args:
            prompt: Input prompt
            **kwargs: Additional parameters (model, temperature, etc.)
            
        Returns:
            Generated text response
        """
        if not self._available:
            return f"[Ollama offline] Processing: {prompt[:50]}..."
        
        try:
            import requests
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": kwargs.get("model", self.model),
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": kwargs.get("temperature", 0.7),
                        "num_predict": kwargs.get("max_tokens", 500),
                    }
                },
                timeout=self.timeout,
            )
            return response.json().get("response", "")
        except Exception as e:
            return f"Ollama error: {str(e)}"
    
    def list_models(self) -> Dict[str, Any]:
        """List available models."""
        if not self._available:
            return {"models": []}
        
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.json()
        except Exception as e:
            return {"error": str(e)}


def create_ollama_client(
    base_url: str = "http://localhost:11434",
    model: str = "llama3:70b",
) -> OllamaClient:
    """Create and return an Ollama client."""
    return OllamaClient(base_url=base_url, model=model)