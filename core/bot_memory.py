"""
Ron Assistant - Bot Memory System
Persistent memory for maintaining context across conversations
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import hashlib


class BotMemory:
    """
    Persistent memory system for the bot to remember:
    - Analyzed files and their content
    - Created files and their purpose
    - Conversation context and history
    - Current project workspace
    """
    
    def __init__(self, memory_dir: str = None):
        """Initialize memory system with storage directory"""
        if memory_dir is None:
            # Default to user's AppData or home directory
            if os.name == 'nt':  # Windows
                base = os.environ.get('APPDATA', os.path.expanduser('~'))
            else:  # Linux/Mac
                base = os.path.expanduser('~/.config')
            memory_dir = os.path.join(base, 'RonAssistant', 'memory')
        
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        # Memory stores
        self.analyzed_files: Dict[str, Dict] = {}
        self.created_files: Dict[str, Dict] = {}
        self.conversation_context: List[Dict] = []
        self.current_project: Optional[str] = None
        
        # Load existing memory
        self._load_memory()
    
    def _get_file_hash(self, file_path: str) -> str:
        """Generate hash for file to detect changes"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return ""
    
    def _load_memory(self):
        """Load memory from disk"""
        memory_file = self.memory_dir / 'bot_memory.json'
        if memory_file.exists():
            try:
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.analyzed_files = data.get('analyzed_files', {})
                    self.created_files = data.get('created_files', {})
                    self.conversation_context = data.get('conversation_context', [])
                    self.current_project = data.get('current_project')
                print(f"✅ Memoria cargada: {len(self.analyzed_files)} archivos analizados")
            except Exception as e:
                print(f"⚠️ Error cargando memoria: {e}")
    
    def _save_memory(self):
        """Save memory to disk"""
        memory_file = self.memory_dir / 'bot_memory.json'
        try:
            data = {
                'analyzed_files': self.analyzed_files,
                'created_files': self.created_files,
                'conversation_context': self.conversation_context[-500:],  # Keep last 500 items
                'current_project': self.current_project,
                'last_updated': datetime.now().isoformat()
            }
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Error guardando memoria: {e}")
    
    def remember_file_analysis(self, file_path: str, content: str, analysis: Dict):
        """
        Store analysis of a file for future reference
        
        Args:
            file_path: Path to the analyzed file
            content: File content
            analysis: Analysis results (structure, dependencies, etc.)
        """
        file_path = os.path.abspath(file_path)
        
        self.analyzed_files[file_path] = {
            'content_hash': hashlib.md5(content.encode()).hexdigest(),
            'analysis': analysis,
            'timestamp': datetime.now().isoformat(),
            'language': self._detect_language(file_path),
            'size': len(content),
            'lines': len(content.split('\n'))
        }
        
        self._save_memory()
        print(f"💾 Análisis guardado: {os.path.basename(file_path)}")
    
    def remember_created_file(self, file_path: str, purpose: str, dependencies: List[str] = None):
        """
        Remember a file that was created
        
        Args:
            file_path: Path to created file
            purpose: Why this file was created
            dependencies: List of files/modules this depends on
        """
        file_path = os.path.abspath(file_path)
        
        self.created_files[file_path] = {
            'purpose': purpose,
            'dependencies': dependencies or [],
            'created_at': datetime.now().isoformat(),
            'file_hash': self._get_file_hash(file_path)
        }
        
        self._save_memory()
        print(f"📝 Archivo registrado: {os.path.basename(file_path)}")
    
    def add_to_context(self, action: str, details: Dict):
        """
        Add an action to conversation context
        
        Args:
            action: Type of action (analyze, create, modify, etc.)
            details: Details about the action
        """
        self.conversation_context.append({
            'action': action,
            'details': details,
            'timestamp': datetime.now().isoformat()
        })
        
        # Keep only last 500 items in memory
        if len(self.conversation_context) > 500:
            self.conversation_context = self.conversation_context[-500:]
        
        self._save_memory()
    
    def set_current_project(self, project_path: str):
        """Set the current working project directory"""
        self.current_project = os.path.abspath(project_path)
        self._save_memory()
        print(f"📁 Proyecto actual: {self.current_project}")
    
    def get_file_analysis(self, file_path: str) -> Optional[Dict]:
        """Retrieve previous analysis of a file"""
        file_path = os.path.abspath(file_path)
        return self.analyzed_files.get(file_path)
    
    def get_context_for_request(self, user_request: str) -> Dict[str, Any]:
        """
        Get relevant context for a user request
        
        Returns:
            Dictionary with relevant files, history, and project info
        """
        # Find relevant files based on request keywords
        relevant_files = self._find_relevant_files(user_request)
        
        # Get recent actions
        recent_actions = self.conversation_context[-10:]
        
        return {
            'relevant_files': relevant_files,
            'recent_history': recent_actions,
            'current_project': self.current_project,
            'total_analyzed_files': len(self.analyzed_files),
            'total_created_files': len(self.created_files)
        }
    
    def _find_relevant_files(self, query: str) -> List[Dict]:
        """Find files relevant to a query"""
        query_lower = query.lower()
        relevant = []
        
        for file_path, data in self.analyzed_files.items():
            # Check if file path or analysis mentions query terms
            if (query_lower in file_path.lower() or 
                any(query_lower in str(v).lower() for v in data.get('analysis', {}).values())):
                relevant.append({
                    'path': file_path,
                    'language': data.get('language'),
                    'analyzed_at': data.get('timestamp')
                })
        
        return relevant[:5]  # Return top 5 most relevant
    
    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension"""
        ext = os.path.splitext(file_path)[1].lower()
        
        language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.cs': 'csharp',
            '.go': 'go',
            '.rs': 'rust',
            '.rb': 'ruby',
            '.php': 'php',
            '.html': 'html',
            '.css': 'css',
            '.json': 'json',
            '.xml': 'xml',
            '.md': 'markdown'
        }
        
        return language_map.get(ext, 'unknown')
    
    def get_summary(self) -> str:
        """Get a summary of current memory state"""
        return f"""
📊 Estado de la Memoria del Bot:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📁 Proyecto actual: {self.current_project or 'Ninguno'}
📄 Archivos analizados: {len(self.analyzed_files)}
✏️  Archivos creados: {len(self.created_files)}
💬 Acciones en contexto: {len(self.conversation_context)}
📂 Ubicación memoria: {self.memory_dir}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    def clear_memory(self):
        """Clear all memory (use with caution)"""
        self.analyzed_files = {}
        self.created_files = {}
        self.conversation_context = []
        self.current_project = None
        self._save_memory()
        print("🗑️ Memoria limpiada")


# Global instance
_memory_instance = None

def get_memory() -> BotMemory:
    """Get or create global memory instance"""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = BotMemory()
    return _memory_instance


if __name__ == '__main__':
    # Test the memory system
    memory = BotMemory()
    print(memory.get_summary())
    
    # Example usage
    memory.set_current_project("C:/Users/LMAR/Desktop/dominopro")
    memory.remember_file_analysis(
        "C:/Users/LMAR/Desktop/dominopro/domino_game.py",
        "import tkinter...",
        {
            'type': 'GUI Application',
            'framework': 'tkinter',
            'complexity': 'medium'
        }
    )
    
    print(memory.get_summary())
