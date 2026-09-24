# CS2 Automated Analytics & RPA Framework

![Project Logo](assets/logo.png)

## Overview
A robust client-server RPA framework designed for automated data extraction, real-time inventory parsing, and secure data management. Engineered to optimize routine analytical workflows, this project processes live environmental states and aggregates market data through a high-performance backend, delivering instant visual insights via a hardware-accelerated GUI overlay.

## Key Features
Utilizes local Game State Integration and asynchronous log parsing to dynamically monitor and extract target entity identifiers. The backend manages a pool of third-party API keys with automated rotation, cooldown enforcement, and rate-limit bypassing to ensure high availability. Built-in core security module that cryptographically binds client execution to specific motherboard and registry component. Comprehensive PyQt5 administration panel for managing access, monitoring API load, and securely distributing software via Telegram-bot integration. Also transparent, frameless PyQt5 interface with global hotkey support, designed to display aggregated data without interrupting the primary workflow

## Tech Stack
**Python 3.11, FastAPI, Uvicorn, SQLite, PyQt5, SHA-256 Request Signatures, HWID Binding**

