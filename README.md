# CS2 Automated Analytics & RPA Framework

![Project Logo](assets/logo.png)

## Overview
A robust client-server RPA (Robotic Process Automation) framework designed for automated data extraction, real-time inventory parsing, and secure data management. Engineered to optimize routine analytical workflows, this project processes live environmental states (GSI) and aggregates market data through a high-performance backend, delivering instant visual insights via a hardware-accelerated GUI overlay.

## Key Features
* **Real-Time State Extraction:** Utilizes local Game State Integration (GSI) and asynchronous log parsing to dynamically monitor and extract target entity identifiers.
* **Advanced API Load Balancing:** The backend manages a pool of third-party API keys with automated rotation, cooldown enforcement, and rate-limit bypassing to ensure high availability.
* **Hardware-ID (HWID) Licensing:** Built-in core security module that cryptographically binds client execution to specific motherboard and registry components (OpSec & Anti-Piracy).
* **Admin Dashboard & Provisioning:** Comprehensive PyQt5 administration panel for managing access, monitoring API load, and securely distributing software via Telegram-bot integration.
* **Non-Intrusive Overlay GUI:** A transparent, frameless PyQt5 interface with global hotkey support, designed to display aggregated data without interrupting the primary workflow.

## Tech Stack
* **Language:** Python 3.x
* **Backend:** FastAPI, Uvicorn (REST API architecture)
* **Database:** SQLite (Scalable to PostgreSQL)
* **Client UI:** PyQt5 (Custom multi-threaded GUI)
* **Security:** SHA-256 Request Signatures, HWID Binding

## Security & Architecture
To maintain strict Operational Security (OpSec) and prevent unauthorized access, this repository serves as an architectural showcase. 
* Compiled `.exe` files, active databases, and sensitive environment variables are strictly excluded. 
* All client-server communications require time-based cryptographic signatures (`X-App-Signature`) to mitigate replay attacks.
* The system utilizes a decoupled `.env` architecture for safe local deployment.
