"""Read-only integration check: no passwords/hashes/user records are printed."""
import json
from app.config import Settings
from app.aitrol_identity import AitrolIdentityProvider, IdentityUnavailable

def main():
    cfg = Settings()
    if cfg.auth_provider != "aitrol": raise SystemExit("Active el proveedor aitrol para esta comprobación.")
    try: result = AitrolIdentityProvider(cfg).probe()
    except IdentityUnavailable as exc:
        print(json.dumps({"identity_source": "aitrol", "status": "unavailable", "stage": exc.stage, "mysql_code": exc.code}))
        raise SystemExit(1) from None
    print(json.dumps(result))

if __name__ == "__main__": main()
