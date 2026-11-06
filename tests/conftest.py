import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "ADK_Agentic"

for path in (ROOT, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _install_pil_stub() -> None:
    if "PIL" in sys.modules:
        return

    pil_module = types.ModuleType("PIL")

    class _ImageModule:
        @staticmethod
        def open(*args, **kwargs):
            raise RuntimeError("Pillow is not installed in this test environment")

    pil_module.Image = _ImageModule
    sys.modules["PIL"] = pil_module


def _install_azure_docintel_stub() -> None:
    if "azure.ai.documentintelligence" in sys.modules:
        return

    try:
        azure_module = importlib.import_module("azure")
    except ModuleNotFoundError:
        azure_module = types.ModuleType("azure")
        sys.modules["azure"] = azure_module

    try:
        ai_module = importlib.import_module("azure.ai")
    except ModuleNotFoundError:
        ai_module = types.ModuleType("azure.ai")
        sys.modules["azure.ai"] = ai_module

    docintel_module = types.ModuleType("azure.ai.documentintelligence")
    models_module = types.ModuleType("azure.ai.documentintelligence.models")
    core_module = types.ModuleType("azure.core")
    credentials_module = types.ModuleType("azure.core.credentials")

    class DocumentIntelligenceClient:
        def __init__(self, *args, **kwargs):
            pass

        def begin_analyze_document(self, *args, **kwargs):
            raise RuntimeError("DocumentIntelligenceClient test stub was not patched")

    class AnalyzeDocumentRequest:
        def __init__(self, bytes_source=None):
            self.bytes_source = bytes_source

    class AzureKeyCredential:
        def __init__(self, key):
            self.key = key

    docintel_module.DocumentIntelligenceClient = DocumentIntelligenceClient
    models_module.AnalyzeDocumentRequest = AnalyzeDocumentRequest
    credentials_module.AzureKeyCredential = AzureKeyCredential

    setattr(azure_module, "ai", ai_module)
    setattr(azure_module, "core", core_module)
    ai_module.documentintelligence = docintel_module
    core_module.credentials = credentials_module

    sys.modules["azure.ai.documentintelligence"] = docintel_module
    sys.modules["azure.ai.documentintelligence.models"] = models_module
    sys.modules["azure.core"] = core_module
    sys.modules["azure.core.credentials"] = credentials_module


_install_pil_stub()
_install_azure_docintel_stub()
