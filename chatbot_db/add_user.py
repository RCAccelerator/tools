"""
Tool to add new users to the chatbot database with authentication tokens.
Handles user creation and token generation with secure password hashing.
"""
import uuid
import getpass
import sys
from datetime import datetime, timedelta, UTC

import bcrypt
from sqlalchemy import create_engine, Column, String, TIMESTAMP, Table, MetaData, select, exc
from sqlalchemy.dialects.postgresql import UUID

def main():
    """Entry point for chatbot_db module."""
    database_url = input("Enter your DATABASE URL "
                         "(e.g. postgresql://user:pass@host:port/db): ").strip()
    username = input("Enter username: ").strip()
    email = input("Enter email: ").strip()
    password = getpass.getpass("Enter password (will be hashed): ")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    engine = create_engine(database_url)
    metadata = MetaData()
    users = Table(
        "users", metadata,
        Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        Column("username", String(150), nullable=False, unique=True),
        Column("password_hash", String(255), nullable=False),
        Column("email", String(150), nullable=False)
    )
    tokens = Table(
        "tokens", metadata,
        Column("token", String(64), primary_key=True),
        Column("username", String(50)),
        Column("created_at", TIMESTAMP, default=datetime.now(UTC)),
        Column("expires_at", TIMESTAMP, nullable=False)
    )
    metadata.create_all(engine)
    with engine.connect() as conn:
        user_exists = conn.execute(
            select(users.c.username).where(users.c.username == username)
        ).fetchone()

        if user_exists:
            print(f"Error: User '{username}' already exists. Please choose a different username.")
            sys.exit(1)

    try:
        with engine.begin() as conn:
            user_id = uuid.uuid4()
            conn.execute(users.insert().values(
                id=user_id,
                username=username,
                password_hash=password_hash,
                email=email
            ))

            token_value = uuid.uuid4().hex
            conn.execute(tokens.insert().values(
                token=token_value,
                username=username,
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=30)
            ))

        print(f"\n User '{username}' created with token: {token_value}")
    except exc.IntegrityError as e:
        print("Error: Database integrity error occurred. User may already exist or "
              "there's a constraint violation.")
        print(f"Details: {str(e)}")
        sys.exit(1)
    except (ConnectionError, TimeoutError) as e:
        print(f"Error: An unexpected error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
