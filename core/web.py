import requests
import re
import logging
import json
try:
    from bs4 import BeautifulSoup 
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

logger = logging.getLogger(__name__)

def search_web(query: str, max_results: int = 5):
    """
    Realiza una búsqueda web utilizando un servicio de búsqueda (o scraping básico como fallback).
    Para este entorno, utilizaremos una búsqueda via DuckDuckGo (HTML) que es más permisiva.
    """
    try:
        logger.info(f"🌐 Buscando en la web: {query}")
        # DuckDuckGo HTML search
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        url = f"https://html.duckduckgo.com/html/?q={query}"
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return []

        # Usar BeautifulSoup si está disponible, si no regex
        results = []
        try:
            if HAS_BS4:
                soup = BeautifulSoup(response.text, "html.parser")
                search_results = soup.find_all("div", class_="result")
            else:
                raise ImportError("BS4 not available")
            
            for res in search_results[:max_results]:
                link_tag = res.find("a", class_="result__a")
                snippet_tag = res.find("a", class_="result__snippet")
                
                if link_tag:
                    title = link_tag.get_text()
                    link = link_tag.get("href")
                    # DuckDuckGo links are often proxied, let's clean them if needed
                    if link.startswith("//duckduckgo.com/l/?kh=-1&uddg="):
                        link = link.split("uddg=")[1].split("&")[0]
                        from urllib.parse import unquote
                        link = unquote(link)
                        
                    snippet = snippet_tag.get_text() if snippet_tag else ""
                    results.append({
                        "title": title,
                        "link": link,
                        "snippet": snippet
                    })
        except Exception as e:
            logger.warning(f"Error parsing with BS4: {e}. Falling back to regex.")
            # Regex fallback (very basic)
            links = re.findall(r'class="result__a" href="([^"]+)">([^<]+)</a>', response.text)
            for link, title in links[:max_results]:
                results.append({
                    "title": title,
                    "link": link,
                    "snippet": "" # Harder to get snippet with simple regex
                })

        return results
    except Exception as e:
        logger.error(f"Error en search_web: {e}")
        return []

def scrape_page(url: str, max_chars: int = 5000):
    """
    Extrae el contenido de texto de una página web.
    """
    try:
        logger.info(f"📄 Scrapeando página: {url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return f"Error: No se pudo acceder a la página (Status {response.status_code})"

        try:
            if HAS_BS4:
                soup = BeautifulSoup(response.text, "html.parser")
            else:
                raise ImportError("BS4 not available")
            # Eliminar scripts y estilos
            for script_or_style in soup(["script", "style", "nav", "footer", "header"]):
                script_or_style.decompose()
            
            # Obtener texto
            text = soup.get_text(separator=' ')
            # Limpiar espacios
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            return text[:max_chars]
        except Exception as e:
            logger.warning(f"Error parsing page with BS4: {e}")
            # Fallback a limpieza de HTML básica con regex
            text = re.sub(r'<[^>]+>', ' ', response.text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]

    except Exception as e:
        logger.error(f"Error en scrape_page: {e}")
        return f"Error al leer la página: {str(e)}"
