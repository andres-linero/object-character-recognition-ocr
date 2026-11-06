"""
Configuration loader — Azure Key Vault with .env fallback.

Loads secrets from the explicitly configured Azure Key Vault.
If Key Vault is unavailable (no Azure login, no network, etc.),
falls back to reading from .env file.

Requires: pip install azure-identity azure-keyvault-secrets
"""

import os
import logging

logger = logging.getLogger(__name__)

VAULT_URL = os.getenv("AZURE_KEY_VAULT_URL", "").strip()

# Map of env var names to Key Vault secret names
# Key Vault doesn't allow underscores, so we use hyphens
SECRET_MAP = {
    "AZURE_DOC_INTEL_ENDPOINT": "AZURE-DOC-INTEL-ENDPOINT",
    "AZURE_DOC_INTEL_KEY": "AZURE-DOC-INTEL-KEY",
    "AZURE_CLIENT_ID": "AZURE-CLIENT-ID",
    "AZURE_CLIENT_SECRET": "AZURE-CLIENT-SECRET",
    "AZURE_TENANT_ID": "AZURE-TENANT-ID",
}


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def load_secrets():
    """
    Load secrets from Azure Key Vault into environment variables.
    Falls back to .env if Key Vault is unavailable.
    """
    # Azure DefaultAzureCredential can block while probing unavailable
    # credentials, so Key Vault is opt-in for deployed environments only.
    if not _env_flag_enabled("USE_AZURE_KEYVAULT"):
        logger.info("Azure Key Vault disabled; using local .env/secrets")
        return False

    if not VAULT_URL:
        raise ValueError("AZURE_KEY_VAULT_URL is required when USE_AZURE_KEYVAULT is enabled")

    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=VAULT_URL, credential=credential)

        loaded = 0
        for env_name, vault_name in SECRET_MAP.items():
            try:
                secret = client.get_secret(vault_name)
                os.environ[env_name] = secret.value
                loaded += 1
            except Exception:
                logger.debug(f"Secret {vault_name} not found in Key Vault")

        if loaded > 0:
            print(f"[OK] Loaded {loaded} secrets from Azure Key Vault")
            return True

    except ImportError:
        logger.info("azure-identity/azure-keyvault-secrets not installed, using .env")
    except Exception as e:
        logger.info(f"Key Vault unavailable ({e}), using .env fallback")

    return False
