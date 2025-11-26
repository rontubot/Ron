"""
Ron Assistant - Folder Analysis System
Comprehensive analysis of project folders and file structures
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Set, Optional
from collections import defaultdict
import re


class FolderAnalyzer:
    """
    Analyzes folder structures to provide:
    - Directory tree visualization
    - File categorization by type
    - Dependency extraction
    - Entry point detection
    - Configuration file identification
    """
    
    # File extensions by category
    CATEGORIES = {
        'python': ['.py', '.pyw', '.pyx'],
        'javascript': ['.js', '.jsx', '.mjs'],
        'typescript': ['.ts', '.tsx'],
        'web': ['.html', '.htm', '.css', '.scss', '.sass', '.less'],
        'config': ['.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf'],
        'data': ['.csv', '.xml', '.sql', '.db', '.sqlite'],
        'docs': ['.md', '.txt', '.rst', '.pdf'],
        'images': ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'],
        'compiled': ['.pyc', '.pyo', '.class', '.o', '.exe', '.dll']
    }
    
    # Common entry point patterns
    ENTRY_POINTS = {
        'python': ['main.py', 'app.py', '__main__.py', 'run.py', 'start.py'],
        'javascript': ['index.js', 'app.js', 'main.js', 'server.js'],
        'web': ['index.html', 'index.htm']
    }
    
    # Directories to skip
    SKIP_DIRS = {
        '__pycache__', 'node_modules', '.git', '.venv', 'venv',
        'env', 'dist', 'build', '.idea', '.vscode', 'target'
    }
    
    def __init__(self, root_path: str):
        """Initialize analyzer with root directory"""
        self.root_path = Path(root_path).resolve()
        if not self.root_path.exists():
            raise ValueError(f"Path does not exist: {root_path}")
        if not self.root_path.is_dir():
            raise ValueError(f"Path is not a directory: {root_path}")
    
    def analyze(self) -> Dict:
        """
        Perform complete folder analysis
        
        Returns:
            Dictionary with all analysis results
        """
        return {
            'structure': self.get_folder_tree(),
            'files_by_type': self.categorize_files(),
            'dependencies': self.extract_dependencies(),
            'entry_points': self.find_entry_points(),
            'config_files': self.find_config_files(),
            'statistics': self.get_statistics()
        }
    
    def get_folder_tree(self, max_depth: int = 5) -> Dict:
        """
        Generate folder tree structure
        
        Args:
            max_depth: Maximum depth to traverse
            
        Returns:
            Nested dictionary representing folder structure
        """
        def build_tree(path: Path, depth: int = 0) -> Dict:
            if depth > max_depth:
                return {'...': 'max depth reached'}
            
            tree = {}
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                
                for item in items:
                    if item.name in self.SKIP_DIRS:
                        continue
                    
                    if item.is_dir():
                        tree[f"📁 {item.name}/"] = build_tree(item, depth + 1)
                    else:
                        size = item.stat().st_size
                        tree[f"📄 {item.name}"] = f"{self._format_size(size)}"
            except PermissionError:
                tree['⚠️'] = 'Permission denied'
            
            return tree
        
        return build_tree(self.root_path)
    
    def categorize_files(self) -> Dict[str, List[str]]:
        """
        Categorize all files by type
        
        Returns:
            Dictionary mapping categories to file lists
        """
        categorized = defaultdict(list)
        
        for file_path in self._walk_files():
            ext = file_path.suffix.lower()
            
            # Find category
            category = 'other'
            for cat, extensions in self.CATEGORIES.items():
                if ext in extensions:
                    category = cat
                    break
            
            relative_path = file_path.relative_to(self.root_path)
            categorized[category].append(str(relative_path))
        
        return dict(categorized)
    
    def extract_dependencies(self) -> Dict[str, Set[str]]:
        """
        Extract dependencies from various file types
        
        Returns:
            Dictionary mapping file types to their dependencies
        """
        dependencies = {
            'python': set(),
            'javascript': set(),
            'npm': set(),
            'pip': set()
        }
        
        for file_path in self._walk_files():
            if file_path.suffix == '.py':
                deps = self._extract_python_imports(file_path)
                dependencies['python'].update(deps)
            
            elif file_path.suffix in ['.js', '.jsx']:
                deps = self._extract_js_imports(file_path)
                dependencies['javascript'].update(deps)
            
            elif file_path.name == 'requirements.txt':
                deps = self._extract_pip_requirements(file_path)
                dependencies['pip'].update(deps)
            
            elif file_path.name == 'package.json':
                deps = self._extract_npm_packages(file_path)
                dependencies['npm'].update(deps)
        
        # Convert sets to sorted lists
        return {k: sorted(list(v)) for k, v in dependencies.items() if v}
    
    def find_entry_points(self) -> Dict[str, List[str]]:
        """
        Find potential entry points for the project
        
        Returns:
            Dictionary mapping entry point types to file paths
        """
        entry_points = defaultdict(list)
        
        for file_path in self._walk_files():
            filename = file_path.name
            
            # Check against known entry point patterns
            for lang, patterns in self.ENTRY_POINTS.items():
                if filename in patterns:
                    relative_path = file_path.relative_to(self.root_path)
                    entry_points[lang].append(str(relative_path))
            
            # Check for if __name__ == '__main__' in Python files
            if file_path.suffix == '.py':
                if self._has_main_guard(file_path):
                    relative_path = file_path.relative_to(self.root_path)
                    if str(relative_path) not in entry_points['python']:
                        entry_points['python'].append(str(relative_path))
        
        return dict(entry_points)
    
    def find_config_files(self) -> List[str]:
        """
        Find all configuration files
        
        Returns:
            List of configuration file paths
        """
        config_files = []
        
        for file_path in self._walk_files():
            if file_path.suffix in self.CATEGORIES['config']:
                relative_path = file_path.relative_to(self.root_path)
                config_files.append(str(relative_path))
        
        return sorted(config_files)
    
    def get_statistics(self) -> Dict:
        """
        Get project statistics
        
        Returns:
            Dictionary with various statistics
        """
        stats = {
            'total_files': 0,
            'total_dirs': 0,
            'total_size': 0,
            'files_by_extension': defaultdict(int),
            'largest_files': []
        }
        
        file_sizes = []
        
        for file_path in self._walk_files():
            stats['total_files'] += 1
            size = file_path.stat().st_size
            stats['total_size'] += size
            
            ext = file_path.suffix or 'no extension'
            stats['files_by_extension'][ext] += 1
            
            file_sizes.append((file_path, size))
        
        # Count directories
        for dir_path in self._walk_dirs():
            stats['total_dirs'] += 1
        
        # Get largest files
        file_sizes.sort(key=lambda x: x[1], reverse=True)
        stats['largest_files'] = [
            {
                'path': str(f.relative_to(self.root_path)),
                'size': self._format_size(s)
            }
            for f, s in file_sizes[:10]
        ]
        
        stats['files_by_extension'] = dict(stats['files_by_extension'])
        stats['total_size_formatted'] = self._format_size(stats['total_size'])
        
        return stats
    
    def _walk_files(self):
        """Generator for all files in directory"""
        for root, dirs, files in os.walk(self.root_path):
            # Skip certain directories
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            
            for filename in files:
                yield Path(root) / filename
    
    def _walk_dirs(self):
        """Generator for all directories"""
        for root, dirs, _ in os.walk(self.root_path):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            
            for dirname in dirs:
                yield Path(root) / dirname
    
    def _extract_python_imports(self, file_path: Path) -> Set[str]:
        """Extract import statements from Python file"""
        imports = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    
                    # Match: import module
                    if line.startswith('import '):
                        module = line[7:].split()[0].split('.')[0]
                        imports.add(module)
                    
                    # Match: from module import ...
                    elif line.startswith('from '):
                        match = re.match(r'from\s+(\S+)', line)
                        if match:
                            module = match.group(1).split('.')[0]
                            imports.add(module)
        except:
            pass
        
        return imports
    
    def _extract_js_imports(self, file_path: Path) -> Set[str]:
        """Extract import/require statements from JavaScript file"""
        imports = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                # Match: import ... from 'module'
                for match in re.finditer(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", content):
                    imports.add(match.group(1))
                
                # Match: require('module')
                for match in re.finditer(r"require\(['\"]([^'\"]+)['\"]\)", content):
                    imports.add(match.group(1))
        except:
            pass
        
        return imports
    
    def _extract_pip_requirements(self, file_path: Path) -> Set[str]:
        """Extract packages from requirements.txt"""
        packages = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Extract package name (before ==, >=, etc.)
                        package = re.split(r'[=<>!]', line)[0].strip()
                        packages.add(package)
        except:
            pass
        
        return packages
    
    def _extract_npm_packages(self, file_path: Path) -> Set[str]:
        """Extract packages from package.json"""
        packages = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                for dep_type in ['dependencies', 'devDependencies']:
                    if dep_type in data:
                        packages.update(data[dep_type].keys())
        except:
            pass
        
        return packages
    
    def _has_main_guard(self, file_path: Path) -> bool:
        """Check if Python file has if __name__ == '__main__' guard"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                return '__name__' in content and '__main__' in content
        except:
            return False
    
    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
    
    def generate_report(self) -> str:
        """
        Generate a formatted text report of the analysis
        
        Returns:
            Formatted string report
        """
        analysis = self.analyze()
        
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║  ANÁLISIS DE CARPETA: {self.root_path.name}
╚══════════════════════════════════════════════════════════════╝

📊 ESTADÍSTICAS GENERALES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total de archivos: {analysis['statistics']['total_files']}
  Total de carpetas: {analysis['statistics']['total_dirs']}
  Tamaño total: {analysis['statistics']['total_size_formatted']}

📁 ESTRUCTURA DEL PROYECTO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{self._format_tree(analysis['structure'])}

📄 ARCHIVOS POR TIPO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        for category, files in sorted(analysis['files_by_type'].items()):
            report += f"\n  {category.upper()} ({len(files)} archivos):\n"
            for file in files[:5]:  # Show first 5
                report += f"    • {file}\n"
            if len(files) > 5:
                report += f"    ... y {len(files) - 5} más\n"
        
        if analysis['entry_points']:
            report += "\n🚀 PUNTOS DE ENTRADA\n"
            report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for lang, files in analysis['entry_points'].items():
                report += f"\n  {lang.upper()}:\n"
                for file in files:
                    report += f"    ▶ {file}\n"
        
        if analysis['dependencies']:
            report += "\n📦 DEPENDENCIAS DETECTADAS\n"
            report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for dep_type, deps in analysis['dependencies'].items():
                if deps:
                    report += f"\n  {dep_type.upper()} ({len(deps)}):\n"
                    for dep in deps[:10]:  # Show first 10
                        report += f"    • {dep}\n"
                    if len(deps) > 10:
                        report += f"    ... y {len(deps) - 10} más\n"
        
        if analysis['config_files']:
            report += "\n⚙️  ARCHIVOS DE CONFIGURACIÓN\n"
            report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for config in analysis['config_files']:
                report += f"  • {config}\n"
        
        report += "\n" + "═" * 64 + "\n"
        
        return report
    
    def _format_tree(self, tree: Dict, indent: str = "", is_last: bool = True) -> str:
        """Format tree dictionary as ASCII tree"""
        lines = []
        items = list(tree.items())
        
        for i, (name, value) in enumerate(items):
            is_last_item = (i == len(items) - 1)
            
            # Tree characters
            if indent == "":
                prefix = ""
            else:
                prefix = indent + ("└── " if is_last_item else "├── ")
            
            lines.append(prefix + name)
            
            # Recursively format subdirectories
            if isinstance(value, dict):
                extension = indent + ("    " if is_last_item else "│   ")
                lines.append(self._format_tree(value, extension, is_last_item))
        
        return "\n".join(lines)


if __name__ == '__main__':
    # Test the analyzer
    import sys
    
    if len(sys.argv) > 1:
        folder_path = sys.argv[1]
    else:
        folder_path = "."
    
    analyzer = FolderAnalyzer(folder_path)
    print(analyzer.generate_report())
