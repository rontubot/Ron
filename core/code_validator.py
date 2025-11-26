"""
Ron Assistant - Code Validator
Validates code completeness, syntax, and quality before saving
"""

import ast
import re
from typing import Dict, List, Tuple, Optional
from pathlib import Path


class CodeValidator:
    """
    Validates code to ensure it's:
    - Syntactically correct
    - Complete (no truncation)
    - Properly formatted
    - Free of common errors
    """
    
    def __init__(self):
        self.validation_results = []
    
    def validate_python(self, code: str) -> Dict:
        """
        Validate Python code
        
        Returns:
            Dictionary with validation results
        """
        results = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'metrics': {}
        }
        
        # 1. Check for syntax errors
        syntax_check = self._check_python_syntax(code)
        if not syntax_check['valid']:
            results['is_valid'] = False
            results['errors'].append(f"Syntax error: {syntax_check['error']}")
        
        # 2. Check completeness
        completeness = self._check_python_completeness(code)
        if not completeness['complete']:
            results['is_valid'] = False
            results['errors'].extend(completeness['issues'])
        
        # 3. Check for common issues
        common_issues = self._check_python_common_issues(code)
        results['warnings'].extend(common_issues)
        
        # 4. Calculate metrics
        results['metrics'] = {
            'lines': len(code.split('\n')),
            'characters': len(code),
            'functions': code.count('def '),
            'classes': code.count('class '),
            'imports': code.count('import ')
        }
        
        return results
    
    def validate_javascript(self, code: str) -> Dict:
        """
        Validate JavaScript code
        
        Returns:
            Dictionary with validation results
        """
        results = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'metrics': {}
        }
        
        # 1. Check completeness
        completeness = self._check_js_completeness(code)
        if not completeness['complete']:
            results['is_valid'] = False
            results['errors'].extend(completeness['issues'])
        
        # 2. Check for common issues
        common_issues = self._check_js_common_issues(code)
        results['warnings'].extend(common_issues)
        
        # 3. Calculate metrics
        results['metrics'] = {
            'lines': len(code.split('\n')),
            'characters': len(code),
            'functions': len(re.findall(r'function\s+\w+', code)) + len(re.findall(r'=>', code)),
            'classes': code.count('class '),
            'imports': code.count('import ') + code.count('require(')
        }
        
        return results
    
    def validate_code(self, code: str, language: str) -> Dict:
        """
        Validate code based on language
        
        Args:
            code: Code to validate
            language: Programming language (python, javascript, etc.)
            
        Returns:
            Validation results dictionary
        """
        language = language.lower()
        
        if language in ['python', 'py']:
            return self.validate_python(code)
        elif language in ['javascript', 'js', 'jsx']:
            return self.validate_javascript(code)
        else:
            return {
                'is_valid': True,
                'errors': [],
                'warnings': [f'No validator available for {language}'],
                'metrics': {'lines': len(code.split('\n'))}
            }
    
    def _check_python_syntax(self, code: str) -> Dict:
        """Check Python syntax using AST"""
        try:
            ast.parse(code)
            return {'valid': True, 'error': None}
        except SyntaxError as e:
            return {
                'valid': False,
                'error': f"Line {e.lineno}: {e.msg}"
            }
        except Exception as e:
            return {
                'valid': False,
                'error': str(e)
            }
    
    def _check_python_completeness(self, code: str) -> Dict:
        """Check if Python code is complete"""
        issues = []
        
        # Check for unmatched brackets/parentheses
        brackets = {'(': ')', '[': ']', '{': '}'}
        stack = []
        
        for char in code:
            if char in brackets.keys():
                stack.append(char)
            elif char in brackets.values():
                if not stack:
                    issues.append("Unmatched closing bracket")
                    break
                expected = brackets[stack.pop()]
                if char != expected:
                    issues.append(f"Mismatched brackets: expected {expected}, got {char}")
                    break
        
        if stack:
            issues.append(f"Unclosed brackets: {len(stack)} opening bracket(s) not closed")
        
        # Check for incomplete function/class definitions
        lines = code.split('\n')
        in_def = False
        indent_level = 0
        
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            
            if stripped.startswith('def ') or stripped.startswith('class '):
                in_def = True
                indent_level = len(line) - len(stripped)
            elif in_def and stripped and not line.startswith(' ' * (indent_level + 1)):
                in_def = False
        
        # Check if code ends abruptly
        last_line = lines[-1].strip() if lines else ""
        if last_line and not last_line.endswith((':', ',', ')', ']', '}')):
            # Check if it's a complete statement
            if not any(last_line.startswith(kw) for kw in ['return', 'pass', 'break', 'continue']):
                if '=' not in last_line and 'print' not in last_line:
                    issues.append("Code may be incomplete: last line doesn't end properly")
        
        # Check for truncated strings
        if code.count('"""') % 2 != 0 or code.count("'''") % 2 != 0:
            issues.append("Unclosed triple-quoted string")
        
        return {
            'complete': len(issues) == 0,
            'issues': issues
        }
    
    def _check_js_completeness(self, code: str) -> Dict:
        """Check if JavaScript code is complete"""
        issues = []
        
        # Check for unmatched brackets/parentheses
        brackets = {'(': ')', '[': ']', '{': '}'}
        stack = []
        in_string = False
        string_char = None
        
        for i, char in enumerate(code):
            # Handle strings
            if char in ['"', "'", '`'] and (i == 0 or code[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
            
            if not in_string:
                if char in brackets.keys():
                    stack.append(char)
                elif char in brackets.values():
                    if not stack:
                        issues.append("Unmatched closing bracket")
                        break
                    expected = brackets[stack.pop()]
                    if char != expected:
                        issues.append(f"Mismatched brackets")
                        break
        
        if stack:
            issues.append(f"Unclosed brackets: {len(stack)} opening bracket(s) not closed")
        
        if in_string:
            issues.append("Unclosed string literal")
        
        # Check for incomplete function declarations
        if re.search(r'function\s+\w+\s*\([^)]*$', code):
            issues.append("Incomplete function declaration")
        
        return {
            'complete': len(issues) == 0,
            'issues': issues
        }
    
    def _check_python_common_issues(self, code: str) -> List[str]:
        """Check for common Python issues"""
        warnings = []
        
        # Check for incorrect self usage (self; instead of self.)
        if re.search(r'self\s*;', code):
            warnings.append("Found 'self;' - should be 'self.'")
        
        # Check for missing imports
        if 'os.path' in code and 'import os' not in code:
            warnings.append("Using os.path but 'import os' not found")
        
        if 'Path(' in code and 'from pathlib import Path' not in code:
            warnings.append("Using Path but import not found")
        
        # Check for bare except
        if re.search(r'except\s*:', code):
            warnings.append("Bare 'except:' found - consider specifying exception type")
        
        # Check for print statements (might be debug code)
        print_count = code.count('print(')
        if print_count > 5:
            warnings.append(f"Found {print_count} print statements - might be debug code")
        
        return warnings
    
    def _check_js_common_issues(self, code: str) -> List[str]:
        """Check for common JavaScript issues"""
        warnings = []
        
        # Check for console.log (might be debug code)
        log_count = code.count('console.log')
        if log_count > 5:
            warnings.append(f"Found {log_count} console.log statements - might be debug code")
        
        # Check for var usage (should use let/const)
        if re.search(r'\bvar\s+', code):
            warnings.append("Using 'var' - consider using 'let' or 'const'")
        
        # Check for == instead of ===
        if re.search(r'[^=!]==[^=]', code):
            warnings.append("Using '==' - consider using '===' for strict equality")
        
        return warnings
    
    def format_validation_report(self, validation: Dict) -> str:
        """Format validation results as a readable report"""
        status = "✅ VÁLIDO" if validation['is_valid'] else "❌ INVÁLIDO"
        
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║  REPORTE DE VALIDACIÓN: {status}
╚══════════════════════════════════════════════════════════════╝
"""
        
        if validation['errors']:
            report += "\n❌ ERRORES ENCONTRADOS:\n"
            report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for error in validation['errors']:
                report += f"  • {error}\n"
        
        if validation['warnings']:
            report += "\n⚠️  ADVERTENCIAS:\n"
            report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for warning in validation['warnings']:
                report += f"  • {warning}\n"
        
        if validation['metrics']:
            report += "\n📊 MÉTRICAS:\n"
            report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for key, value in validation['metrics'].items():
                report += f"  {key.capitalize()}: {value}\n"
        
        report += "\n" + "═" * 64 + "\n"
        
        return report


class SmartCodeGenerator:
    """
    Generates code with built-in validation and retry logic
    """
    
    def __init__(self):
        self.validator = CodeValidator()
        self.attempts = []
        self.max_attempts = 3
    
    def generate_and_validate(self, code: str, language: str, file_path: str) -> Dict:
        """
        Generate code with validation
        
        Args:
            code: Generated code
            language: Programming language
            file_path: Destination file path
            
        Returns:
            Dictionary with generation results
        """
        # Validate the code
        validation = self.validator.validate_code(code, language)
        
        result = {
            'success': validation['is_valid'],
            'validation': validation,
            'file_path': file_path,
            'saved': False
        }
        
        if validation['is_valid']:
            # Save the file
            try:
                Path(file_path).parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(code)
                result['saved'] = True
                print(f"✅ Archivo guardado: {file_path}")
            except Exception as e:
                result['success'] = False
                result['validation']['errors'].append(f"Error saving file: {e}")
        else:
            print(f"❌ Código no válido, no se guardó el archivo")
            print(self.validator.format_validation_report(validation))
        
        return result
    
    def track_attempt(self, attempt_num: int, validation: Dict):
        """Track generation attempts for learning"""
        self.attempts.append({
            'attempt': attempt_num,
            'validation': validation,
            'errors': validation.get('errors', []),
            'warnings': validation.get('warnings', [])
        })
    
    def get_attempt_summary(self) -> str:
        """Get summary of all attempts"""
        if not self.attempts:
            return "No attempts recorded"
        
        summary = f"\n📝 RESUMEN DE INTENTOS ({len(self.attempts)}):\n"
        summary += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        for attempt in self.attempts:
            status = "✅" if attempt['validation'].get('is_valid') else "❌"
            summary += f"\nIntento #{attempt['attempt']}: {status}\n"
            if attempt['errors']:
                summary += f"  Errores: {len(attempt['errors'])}\n"
                for error in attempt['errors'][:2]:
                    summary += f"    • {error}\n"
        
        return summary


if __name__ == '__main__':
    # Test the validator
    validator = CodeValidator()
    
    # Test Python code
    python_code = """
import os

def hello_world():
    print("Hello, World!")
    return True

class MyClass:
    def __init__(self):
        self.name = "Test"
"""
    
    result = validator.validate_python(python_code)
    print(validator.format_validation_report(result))
    
    # Test incomplete Python code
    incomplete_code = """
def incomplete_function():
    print("This function is not
"""
    
    result = validator.validate_python(incomplete_code)
    print(validator.format_validation_report(result))
