-- Bootstrap script for local PostgreSQL test database setup for Kalido Lite.
-- This script creates the kalido_lite database, a kalido user, and grants privileges.

-- Create role/user "kalido" if it does not already exist.
DO
$$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'kalido'
    ) THEN
        CREATE ROLE kalido LOGIN PASSWORD 'kalido';
    END IF;
END
$$;

-- Create database "kalido_lite" if it does not already exist.
DO
$$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_database WHERE datname = 'kalido_lite'
    ) THEN
        CREATE DATABASE kalido_lite OWNER kalido;
    END IF;
END
$$;

-- Grant all privileges on the kalido_lite database to user "kalido".
GRANT ALL PRIVILEGES ON DATABASE kalido_lite TO kalido;
