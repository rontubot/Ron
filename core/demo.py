"""
Demo Script - Ron Assistant Core Improvements
Demonstrates all the new capabilities
"""

import sys
import os
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add core to path
sys.path.insert(0, str(Path(__file__).parent))

from ron_assistant_core import RonAssistantCore


def print_section(title):
    """Print a formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demo_memory_system(core):
    """Demonstrate the memory system"""
    print_section("DEMO 1: Sistema de Memoria Persistente")
    
    print("📝 Estado inicial de la memoria:")
    print(core.show_memory_status())
    
    # Simulate remembering a file analysis
    print("\n🔍 Simulando análisis de archivo...")
    core.memory.remember_file_analysis(
        "C:/Users/LMAR/Desktop/dominopro/domino_game.py",
        "import tkinter as tk\n\nclass DominoGame:\n    pass",
        {
            'type': 'GUI Application',
            'framework': 'tkinter',
            'classes': 1,
            'functions': 0
        }
    )
    
    print("\n📝 Estado después de analizar archivo:")
    print(core.show_memory_status())
    
    # Simulate creating a file
    print("\n✏️  Simulando creación de archivo...")
    core.memory.remember_created_file(
        "C:/Users/LMAR/Desktop/test.py",
        "Script de prueba para demostración",
        ["os", "sys"]
    )
    
    print("\n📝 Estado después de crear archivo:")
    print(core.show_memory_status())
    
    # Get context for a request
    print("\n🔎 Obteniendo contexto para: 'crear juego de dominó'")
    context = core.get_context("crear juego de dominó")
    print(f"  Archivos relevantes encontrados: {len(context['relevant_files'])}")
    print(f"  Acciones recientes: {len(context['recent_history'])}")
    print(f"  Proyecto actual: {context['current_project']}")


def demo_folder_analysis(core):
    """Demonstrate folder analysis"""
    print_section("DEMO 2: Análisis de Carpetas")
    
    # Analyze the Ron project itself
    project_path = Path(__file__).parent.parent
    print(f"📁 Analizando carpeta: {project_path}")
    
    try:
        report = core.analyze_folder(str(project_path))
        print(report)
    except Exception as e:
        print(f"❌ Error: {e}")


def demo_file_analysis(core):
    """Demonstrate file analysis"""
    print_section("DEMO 3: Análisis de Archivos")
    
    # Analyze this demo file itself
    demo_file = Path(__file__)
    print(f"📄 Analizando archivo: {demo_file.name}")
    
    try:
        report = core.analyze_file(str(demo_file))
        print(report)
    except Exception as e:
        print(f"❌ Error: {e}")


def demo_code_validation(core):
    """Demonstrate code validation"""
    print_section("DEMO 4: Validación de Código")
    
    # Test with valid Python code
    print("✅ Probando código VÁLIDO:")
    valid_code = """
import os

def hello_world():
    print("Hello, World!")
    return True

class MyClass:
    def __init__(self):
        self.name = "Test"
"""
    
    validation = core.validator.validate_python(valid_code)
    print(core.validator.format_validation_report(validation))
    
    # Test with invalid Python code
    print("\n❌ Probando código INVÁLIDO:")
    invalid_code = """
def incomplete_function():
    print("This function is not closed
    # Missing closing quote and bracket
"""
    
    validation = core.validator.validate_python(invalid_code)
    print(core.validator.format_validation_report(validation))


def demo_code_generation(core):
    """Demonstrate code generation with validation"""
    print_section("DEMO 5: Generación de Código con Validación")
    
    # Create a test file
    test_file = Path(__file__).parent / "test_generated.py"
    
    code = """
import sys

def main():
    print("Este es un archivo generado automáticamente")
    print(f"Python version: {sys.version}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
"""
    
    print(f"📝 Creando archivo: {test_file.name}")
    result = core.create_file(
        str(test_file),
        code,
        "python",
        "Archivo de demostración generado automáticamente"
    )
    
    if result['saved']:
        print(f"\n✅ Archivo creado exitosamente!")
        print(f"   Ubicación: {test_file}")
        print(f"   Validación: {result['validation']['is_valid']}")
        print(f"   Líneas: {result['validation']['metrics']['lines']}")
    else:
        print(f"\n❌ Error creando archivo:")
        for error in result['validation']['errors']:
            print(f"   • {error}")


def demo_context_retention(core):
    """Demonstrate context retention across operations"""
    print_section("DEMO 6: Retención de Contexto")
    
    print("🔄 Simulando múltiples operaciones...")
    
    # Operation 1
    print("\n1️⃣  Operación 1: Analizar carpeta")
    core.memory.set_current_project("C:/Users/LMAR/Desktop/dominopro")
    core.memory.add_to_context('analyze_folder', {'path': 'dominopro'})
    
    # Operation 2
    print("2️⃣  Operación 2: Crear archivo")
    core.memory.add_to_context('create_file', {'path': 'domino.py', 'language': 'python'})
    
    # Operation 3
    print("3️⃣  Operación 3: Modificar archivo")
    core.memory.add_to_context('modify_file', {'path': 'domino.py', 'changes': 'Added main function'})
    
    # Show context
    print("\n📊 Contexto acumulado:")
    context = core.get_context("continuar con el proyecto")
    
    print(f"\n  Proyecto actual: {context['current_project']}")
    print(f"  Acciones recientes ({len(context['recent_history'])}):")
    for i, action in enumerate(context['recent_history'][-5:], 1):
        print(f"    {i}. {action['action']}: {action['details']}")


def main():
    """Run all demos"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║  🤖 RON ASSISTANT - DEMOSTRACIÓN DE MEJORAS                     ║
║                                                                  ║
║  Este script demuestra todas las nuevas capacidades del bot:    ║
║  • Sistema de memoria persistente                               ║
║  • Análisis completo de carpetas                                ║
║  • Análisis detallado de archivos                               ║
║  • Validación automática de código                              ║
║  • Generación de código con validación                          ║
║  • Retención de contexto entre operaciones                      ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
""")
    
    # Initialize core
    core = RonAssistantCore()
    
    # Run demos
    try:
        demo_memory_system(core)
        input("\n⏸️  Presiona ENTER para continuar...")
        
        demo_folder_analysis(core)
        input("\n⏸️  Presiona ENTER para continuar...")
        
        demo_file_analysis(core)
        input("\n⏸️  Presiona ENTER para continuar...")
        
        demo_code_validation(core)
        input("\n⏸️  Presiona ENTER para continuar...")
        
        demo_code_generation(core)
        input("\n⏸️  Presiona ENTER para continuar...")
        
        demo_context_retention(core)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Demo interrumpida por el usuario")
    except Exception as e:
        print(f"\n\n❌ Error durante la demo: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("  ✅ Demo completada")
    print("=" * 70)
    print("\n💡 Tip: Revisa el archivo README.md para más información")
    print("📂 Ubicación de memoria:", core.memory.memory_dir)


if __name__ == '__main__':
    main()
