"""
Ron Assistant - Integration Module
Integrates all bot improvement modules for seamless operation
"""

from pathlib import Path
from typing import Dict, Optional
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from bot_memory import BotMemory, get_memory
from folder_analyzer import FolderAnalyzer
from code_validator import CodeValidator, SmartCodeGenerator


class RonAssistantCore:
    """
    Core integration class that brings together all bot improvements:
    - Memory system for context retention
    - Folder analysis for project understanding
    - Code validation for quality assurance
    """
    
    def __init__(self):
        """Initialize all subsystems"""
        self.memory = get_memory()
        self.validator = CodeValidator()
        self.code_generator = SmartCodeGenerator()
        
        print("🤖 Ron Assistant Core inicializado")
        print(self.memory.get_summary())
    
    def analyze_folder(self, folder_path: str) -> str:
        """
        Analyze a complete folder and remember the analysis
        
        Args:
            folder_path: Path to folder to analyze
            
        Returns:
            Formatted analysis report
        """
        try:
            analyzer = FolderAnalyzer(folder_path)
            analysis = analyzer.analyze()
            report = analyzer.generate_report()
            
            # Remember this analysis
            self.memory.set_current_project(folder_path)
            self.memory.add_to_context('analyze_folder', {
                'path': folder_path,
                'files_count': analysis['statistics']['total_files'],
                'dirs_count': analysis['statistics']['total_dirs']
            })
            
            # Store analysis in memory
            self.memory.analyzed_files[folder_path] = {
                'type': 'folder_analysis',
                'analysis': analysis,
                'timestamp': None  # Will be set by memory system
            }
            self.memory._save_memory()
            
            return report
            
        except Exception as e:
            return f"❌ Error analizando carpeta: {e}"
    
    def analyze_file(self, file_path: str) -> str:
        """
        Analyze a single file and remember the analysis
        
        Args:
            file_path: Path to file to analyze
            
        Returns:
            Analysis report
        """
        try:
            file_path = Path(file_path).resolve()
            
            if not file_path.exists():
                return f"❌ Archivo no encontrado: {file_path}"
            
            # Read file content
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Detect language
            language = self.memory._detect_language(str(file_path))
            
            # Validate if it's code
            validation = None
            if language in ['python', 'javascript']:
                validation = self.validator.validate_code(content, language)
            
            # Create analysis
            analysis = {
                'language': language,
                'size': len(content),
                'lines': len(content.split('\n')),
                'validation': validation
            }
            
            # Remember this analysis
            self.memory.remember_file_analysis(str(file_path), content, analysis)
            self.memory.add_to_context('analyze_file', {
                'path': str(file_path),
                'language': language
            })
            
            # Format report
            report = f"""
╔══════════════════════════════════════════════════════════════╗
║  ANÁLISIS DE ARCHIVO: {file_path.name}
╚══════════════════════════════════════════════════════════════╝

📄 INFORMACIÓN GENERAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Ruta: {file_path}
  Lenguaje: {language}
  Tamaño: {len(content)} caracteres
  Líneas: {len(content.split('\n'))}
"""
            
            if validation:
                report += "\n" + self.validator.format_validation_report(validation)
            
            # Show first few lines of content
            lines = content.split('\n')[:20]
            report += "\n📝 CONTENIDO (primeras 20 líneas):\n"
            report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for i, line in enumerate(lines, 1):
                report += f"{i:3d} | {line}\n"
            
            if len(content.split('\n')) > 20:
                report += f"\n... y {len(content.split('\n')) - 20} líneas más\n"
            
            report += "\n" + "═" * 64 + "\n"
            
            return report
            
        except Exception as e:
            return f"❌ Error analizando archivo: {e}"
    
    def create_file(self, file_path: str, content: str, language: str, purpose: str = "") -> Dict:
        """
        Create a file with validation
        
        Args:
            file_path: Where to save the file
            content: File content
            language: Programming language
            purpose: Why this file is being created
            
        Returns:
            Creation result dictionary
        """
        result = self.code_generator.generate_and_validate(content, language, file_path)
        
        if result['saved']:
            # Remember this file
            self.memory.remember_created_file(file_path, purpose)
            self.memory.add_to_context('create_file', {
                'path': file_path,
                'language': language,
                'purpose': purpose
            })
        
        return result
    
    def get_context(self, user_request: str) -> Dict:
        """
        Get relevant context for a user request
        
        Args:
            user_request: What the user is asking for
            
        Returns:
            Context dictionary
        """
        return self.memory.get_context_for_request(user_request)
    
    def get_file_from_memory(self, file_path: str) -> Optional[Dict]:
        """
        Retrieve previous analysis of a file from memory
        
        Args:
            file_path: Path to file
            
        Returns:
            Analysis data if found, None otherwise
        """
        return self.memory.get_file_analysis(file_path)
    
    def show_memory_status(self) -> str:
        """Get current memory status"""
        return self.memory.get_summary()
    
    def clear_memory(self):
        """Clear all memory"""
        self.memory.clear_memory()
        print("🗑️ Memoria del bot limpiada")


# Global instance
_core_instance = None

def get_core() -> RonAssistantCore:
    """Get or create global core instance"""
    global _core_instance
    if _core_instance is None:
        _core_instance = RonAssistantCore()
    return _core_instance


# Convenience functions for easy access
def analyze_folder(folder_path: str) -> str:
    """Analyze a folder"""
    return get_core().analyze_folder(folder_path)

def analyze_file(file_path: str) -> str:
    """Analyze a file"""
    return get_core().analyze_file(file_path)

def create_file(file_path: str, content: str, language: str, purpose: str = "") -> Dict:
    """Create a file with validation"""
    return get_core().create_file(file_path, content, language, purpose)

def get_context(user_request: str) -> Dict:
    """Get context for a request"""
    return get_core().get_context(user_request)

def show_status() -> str:
    """Show memory status"""
    return get_core().show_memory_status()


if __name__ == '__main__':
    # Demo usage
    core = RonAssistantCore()
    
    print("\n" + "="*64)
    print("DEMO: Analizando carpeta del proyecto Ron")
    print("="*64)
    
    # Analyze the Ron project folder
    project_path = Path(__file__).parent.parent
    report = core.analyze_folder(str(project_path))
    print(report)
    
    print("\n" + "="*64)
    print("DEMO: Estado de la memoria")
    print("="*64)
    print(core.show_memory_status())
