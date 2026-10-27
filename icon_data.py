import sys
# -*- coding: utf-8 -*-
"""Icon data (auto-generated)"""
import base64
import os
import tempfile

_ICON_BASE64 = "AAABAAEAEBAAAAAAIAArAwAAFgAAAIlQTkcNChoKAAAADUlIRFIAAAAQAAAAEAgGAAAAH/P/YQAAAvJJREFUeJw10UtvlFUcwOHfOeftO3dmpjOtg4o2kBIBYxMgaYLEjZro2k9gXJv4Vdy6dOcXYEdQF8YaELTILS29YAvtdMrc3tt5zzl/F8Sv8Dxq49lLieIIEcEYg9EaFQICBIEQwAXBOY91gTR3WFtiS09ROiJjNBqhVolRviTPEpTWGKXQKEIQlA+IF4xztCox2UIdP0+JRIgUgXqlxu7OLj/c2uBUYqrNJlRrVKsGYwxp7iBNyZOErir56uZVeoNzTOcpun6miXjL9z/d5vZeyV5eYW/qcbakiyCjEbPxnN1pYC+LubNX8OOtXzFGETe76Hq9xnQ648VpRrtWoSwK3g1j3imEvHAcHp3gNv9gaX5AUVgacczBKCFNpjRadbTPC5S80cpyS18VvF+F7eGYSWSIBm/zbxZYNpZr1QmqSAk+EC8oWk2FjoxGaUVwgXSesdqrsdxQvD7eZTzLmY1nXDr/HmsfXeF8O2KtH5GkBRFvcLWIIMHjS4fLLPPRiGEWWGlrXt+7j995zufrl7l77wH9bpujkwniBBQoo4j+D5/Pci70W7R1xuRoRqtm6JWHrN/4hJ/v/ILNCv5+8pwkFULpcN6TZxbtvSeIUMxTlhuKrPRcurxKpBQXbn5K7+xZVpY6fHzjOokNdOuaIkkpnafIS3SR5TjniIDNh/uIwKP9EWJivrx+kasfrNAYnGP7YIR4z8PHL4kEsiwjTzOiSAVKm+NtwcS2+W1jiyuri3QaFXa293HOs7O1xcnxkL+enpKEt6iE11TslFaoEy122lSM0Kk6jscZ80aXB09mnKlOeOWfooAX/zxjbhcoVY8ySekMPGsfXqTZ7KCDeBb7S3z3zRcMaq9YsMc4W3A6tTy+v8mjPzcZJx5fWkxxxKB6yLdff0a3t4QPATWcpqKVIklTft+4y3A0QSkFSoHSACABJBCC0F9ss75+jWazQfCghpNU0JBlBSIR0UKEoFAIWisAQhAEBQLOORSOWjUmBOE/CPW3F8kmQwwAAAAASUVORK5CYII="

def get_icon_path():
    """Get icon file path"""
    if hasattr(sys, "_custom_icon_path") and sys._custom_icon_path:
        return sys._custom_icon_path
    ico_bytes = base64.b64decode(_ICON_BASE64)
    temp_dir = tempfile.gettempdir()
    icon_path = os.path.join(temp_dir, "app_icon.ico")
    with open(icon_path, "wb") as f:
        f.write(ico_bytes)
    return icon_path
