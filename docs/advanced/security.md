# Advanced: Security Considerations

Security best practices for production Rufus deployments, with focus on PCI-DSS compliance for fintech applications.

---

## PCI-DSS Compliance

### Requirements for Payment Card Processing

**PCI-DSS Level**: Depends on transaction volume
- **Level 1**: > 6M transactions/year (strictest requirements)
- **Level 2-4**: Fewer transactions (lighter requirements)

**Key Requirements:**
1. **Never store sensitive authentication data** (CVV, PIN, magnetic stripe)
2. **Encrypt cardholder data at rest and in transit**
3. **Maintain audit logs** of all access to cardholder data
4. **Implement access controls** (least privilege principle)
5. **Regular security testing** and vulnerability scanning

---

## Data Encryption

### Encrypt Sensitive Data in Workflow State

```python
from cryptography.fernet import Fernet
from pydantic import BaseModel, validator
import os


class SecurePaymentState(BaseModel):
    """State with encrypted card data"""

    # Public fields
    transaction_id: str
    amount: float
    merchant_id: str

    # Encrypted fields (stored as bytes)
    encrypted_card_number: bytes
    encrypted_cvv: bytes

    # Tokenized reference (safe to store)
    card_token: str  # e.g., "tok_1234567890"
    card_last_four: str  # Last 4 digits OK to store

    @classmethod
    def from_card_data(cls, card_number: str, cvv: str, encryption_key: bytes, **kwargs):
        """Create state from plaintext card data"""
        f = Fernet(encryption_key)

        return cls(
            encrypted_card_number=f.encrypt(card_number.encode()),
            encrypted_cvv=f.encrypt(cvv.encode()),
            card_last_four=card_number[-4:],
            **kwargs
        )

    def decrypt_card_number(self, encryption_key: bytes) -> str:
        """Decrypt card number (use sparingly!)"""
        f = Fernet(encryption_key)
        return f.decrypt(self.encrypted_card_number).decode()
```

**Usage:**

```python
# Encryption key from environment (never hardcode!)
ENCRYPTION_KEY = os.getenv("RUFUS_ENCRYPTION_KEY").encode()

# Create workflow with encrypted data
state = SecurePaymentState.from_card_data(
    card_number="4111111111111111",
    cvv="123",
    encryption_key=ENCRYPTION_KEY,
    transaction_id="TXN-001",
    amount=99.99,
    merchant_id="MERCHANT-123",
    card_token="tok_abc123"
)

workflow = builder.create_workflow("Payment", initial_data=state.dict())
```

---

### Key Management

**❌ Never do this:**

```python
# WRONG: Hardcoded encryption key
ENCRYPTION_KEY = b'hardcoded-key-123'
```

**✅ Use environment variables:**

```python
import os

ENCRYPTION_KEY = os.getenv("RUFUS_ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise ValueError("RUFUS_ENCRYPTION_KEY environment variable not set")
```

**✅ Better: Use AWS KMS or HashiCorp Vault:**

```python
import boto3

def get_encryption_key():
    """Fetch encryption key from AWS KMS"""
    kms_client = boto3.client('kms')

    response = kms_client.decrypt(
        CiphertextBlob=os.getenv("ENCRYPTED_KEY_BLOB"),
        EncryptionContext={'Application': 'Rufus'}
    )

    return response['Plaintext']
```

---

## Input Validation

### Validate All User Input

```python
from pydantic import BaseModel, validator, constr, confloat


class PaymentInput(BaseModel):
    """Validated payment input"""

    # Constrained types
    card_number: constr(min_length=13, max_length=19, regex=r'^\d+$')
    amount: confloat(gt=0, lt=1000000)  # > 0, < 1M
    currency: constr(regex=r'^[A-Z]{3}$')  # ISO 4217 currency code

    @validator('card_number')
    def validate_card_number(cls, v):
        """Luhn algorithm validation"""
        def luhn_checksum(card_num):
            def digits_of(n):
                return [int(d) for d in str(n)]
            digits = digits_of(card_num)
            odd_digits = digits[-1::-2]
            even_digits = digits[-2::-2]
            checksum = sum(odd_digits)
            for d in even_digits:
                checksum += sum(digits_of(d*2))
            return checksum % 10

        if luhn_checksum(v) != 0:
            raise ValueError('Invalid card number (Luhn check failed)')
        return v

    @validator('currency')
    def validate_currency(cls, v):
        """Only allow specific currencies"""
        allowed_currencies = {'USD', 'EUR', 'GBP', 'CAD'}
        if v not in allowed_currencies:
            raise ValueError(f'Currency must be one of {allowed_currencies}')
        return v
```

**Use in workflow:**

```python
def process_payment(state: PaymentState, context: StepContext, **user_input) -> dict:
    """Process payment with validated input"""

    # Validate input
    try:
        payment_input = PaymentInput(**user_input)
    except ValidationError as e:
        raise ValueError(f"Invalid payment input: {e}")

    # Process payment
    # ...
```

---

## Access Control

### API Key Management

```python
import secrets
import hashlib
from datetime import datetime, timedelta


class APIKeyManager:
    """Manage API keys for device authentication"""

    def __init__(self, persistence_provider):
        self.persistence = persistence_provider

    def generate_api_key(self, device_id: str, expires_days: int = 365) -> str:
        """Generate new API key for device"""
        # Generate secure random key
        api_key = secrets.token_urlsafe(32)

        # Hash for storage (never store plaintext!)
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Store hashed key
        expiry = datetime.utcnow() + timedelta(days=expires_days)
        await self.persistence.store_api_key(
            device_id=device_id,
            key_hash=key_hash,
            expires_at=expiry
        )

        return api_key  # Return once, never store!

    async def validate_api_key(self, device_id: str, api_key: str) -> bool:
        """Validate API key"""
        # Hash provided key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Check against stored hash
        stored = await self.persistence.get_api_key(device_id)

        if not stored:
            return False

        # Check expiry
        if stored['expires_at'] < datetime.utcnow():
            return False

        # Compare hashes (timing-safe)
        return secrets.compare_digest(stored['key_hash'], key_hash)
```

---

### Role-Based Access Control (RBAC)

```python
from enum import Enum


class Role(Enum):
    """User roles"""
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Permission(Enum):
    """Permissions"""
    CREATE_WORKFLOW = "create_workflow"
    VIEW_WORKFLOW = "view_workflow"
    CANCEL_WORKFLOW = "cancel_workflow"
    VIEW_LOGS = "view_logs"
    MANAGE_DEVICES = "manage_devices"


# Role-permission mapping
ROLE_PERMISSIONS = {
    Role.ADMIN: {
        Permission.CREATE_WORKFLOW,
        Permission.VIEW_WORKFLOW,
        Permission.CANCEL_WORKFLOW,
        Permission.VIEW_LOGS,
        Permission.MANAGE_DEVICES,
    },
    Role.OPERATOR: {
        Permission.CREATE_WORKFLOW,
        Permission.VIEW_WORKFLOW,
        Permission.CANCEL_WORKFLOW,
        Permission.VIEW_LOGS,
    },
    Role.VIEWER: {
        Permission.VIEW_WORKFLOW,
        Permission.VIEW_LOGS,
    }
}


def check_permission(user_role: Role, required_permission: Permission) -> bool:
    """Check if user role has permission"""
    return required_permission in ROLE_PERMISSIONS.get(user_role, set())


# Decorator for permission checks
def require_permission(permission: Permission):
    def decorator(func):
        async def wrapper(user, *args, **kwargs):
            if not check_permission(user.role, permission):
                raise PermissionError(f"User lacks permission: {permission.value}")
            return await func(user, *args, **kwargs)
        return wrapper
    return decorator


# Usage
@require_permission(Permission.CANCEL_WORKFLOW)
async def cancel_workflow(user, workflow_id: str):
    """Cancel workflow (requires permission)"""
    # ...
```

---

## Audit Logging

### Comprehensive Audit Trail

```python
async def audit_log(
    persistence: PersistenceProvider,
    event_type: str,
    user_id: str,
    workflow_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """Log security-relevant event"""
    await persistence.audit_log(
        event_type=event_type,
        user_id=user_id,
        workflow_id=workflow_id,
        timestamp=datetime.utcnow(),
        ip_address=get_client_ip(),
        details=details or {}
    )


# Log all security events
await audit_log(
    persistence=persistence,
    event_type="WORKFLOW_CREATED",
    user_id=user.id,
    workflow_id=workflow.id,
    details={"workflow_type": workflow.workflow_type}
)

await audit_log(
    persistence=persistence,
    event_type="API_KEY_GENERATED",
    user_id=user.id,
    details={"device_id": device_id}
)

await audit_log(
    persistence=persistence,
    event_type="UNAUTHORIZED_ACCESS_ATTEMPT",
    user_id=user.id,
    details={"attempted_workflow_id": workflow_id}
)
```

---

## Network Security

### TLS/SSL for API Communication

```python
# Production: Always use HTTPS
CLOUD_URL = "https://api.example.com"  # ✅

# Development: HTTP OK for localhost only
if os.getenv("ENVIRONMENT") == "development":
    CLOUD_URL = "http://localhost:8000"  # OK for local dev
```

### Certificate Pinning (Edge Devices)

```python
import httpx


def create_secure_client():
    """Create HTTP client with certificate pinning"""
    return httpx.AsyncClient(
        verify="/path/to/ca-cert.pem",  # Custom CA certificate
        timeout=30.0
    )


# Usage
async with create_secure_client() as client:
    response = await client.post(
        f"{CLOUD_URL}/api/v1/sync",
        json=data,
        headers={"X-API-Key": API_KEY}
    )
```

---

## Secrets Management

### Never Commit Secrets

**❌ Bad: Secrets in code**

```python
API_KEY = "sk_live_abc123"  # NEVER DO THIS
DB_PASSWORD = "password123"
```

**✅ Good: Environment variables**

```bash
# .env (add to .gitignore!)
RUFUS_API_KEY=sk_live_abc123
DB_PASSWORD=password123
ENCRYPTION_KEY=fernet-key-here
```

```python
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("RUFUS_API_KEY")
DB_PASSWORD = os.getenv("DB_PASSWORD")
```

---

### Use Secrets Manager (Production)

```python
import boto3


def get_secret(secret_name: str) -> str:
    """Fetch secret from AWS Secrets Manager"""
    client = boto3.client('secretsmanager')

    response = client.get_secret_value(SecretId=secret_name)

    return response['SecretString']


# Usage
DB_PASSWORD = get_secret("rufus/db/password")
API_KEY = get_secret("rufus/api/key")
```

---

## Security Checklist

### Deployment Checklist

- [ ] **Encryption**
  - [ ] All sensitive data encrypted at rest
  - [ ] TLS/SSL for all network communication
  - [ ] Encryption keys in secure key management system

- [ ] **Authentication**
  - [ ] API keys hashed (never store plaintext)
  - [ ] API key rotation implemented
  - [ ] Rate limiting on authentication endpoints

- [ ] **Authorization**
  - [ ] Role-based access control (RBAC) implemented
  - [ ] Least privilege principle enforced
  - [ ] Permission checks on all sensitive operations

- [ ] **Audit Logging**
  - [ ] All security events logged
  - [ ] Logs include user ID, timestamp, IP address
  - [ ] Logs tamper-proof (write-only)

- [ ] **Input Validation**
  - [ ] All user input validated with Pydantic
  - [ ] SQL injection prevention (parameterized queries)
  - [ ] XSS prevention (if web UI)

- [ ] **Secrets Management**
  - [ ] No secrets in code or version control
  - [ ] Secrets in environment variables or vault
  - [ ] Secrets rotation policy

- [ ] **Network Security**
  - [ ] HTTPS only in production
  - [ ] Certificate pinning for edge devices
  - [ ] Firewall rules restricting access

- [ ] **Compliance**
  - [ ] PCI-DSS compliance (if processing payments)
  - [ ] GDPR compliance (if processing EU user data)
  - [ ] Regular security audits

---

## Vulnerability Scanning

### Regular Security Scans

```bash
# Scan Python dependencies
pip install safety
safety check

# Scan for secrets in code
pip install detect-secrets
detect-secrets scan

# Static analysis
pip install bandit
bandit -r src/
```

---

## Summary

**Security Principles:**
1. **Encrypt everything** (at rest and in transit)
2. **Validate all input** (use Pydantic)
3. **Never store secrets** in code
4. **Log all security events** (audit trail)
5. **Implement access control** (RBAC)
6. **Regular security scanning** (dependencies, code)

**For PCI-DSS compliance**, consult with a Qualified Security Assessor (QSA).
