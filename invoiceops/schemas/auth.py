"""Public identity response; never includes access or refresh tokens."""

from pydantic import BaseModel

from invoiceops.auth import Role


class PrincipalRead(BaseModel):
    subject: str
    roles: list[Role]
