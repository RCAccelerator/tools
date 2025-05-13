# User and Token creation script for RCAccelerator

This Python script creates a user and an associated access token in a PostgreSQL database, based on a schema with `users` and `tokens` tables. It is designed for RCAccelerator, to be interactive and secure, using bcrypt for password hashing.

Run the script:

```bash
python add_user.py
```

You will be prompted for:

* The PostgreSQL DATABASE_URL (format: postgresql://user:pass@host:port/dbname)
* The username and email of the user
* The password (input hidden)

A hashed password will be stored in the users table, and a 30-days token will be created in the tokens table.
