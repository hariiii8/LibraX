# LibraX — Library Management System

A web-based Library Management System built with Python Flask and Oracle SQL XE.

## Tech Stack
- Backend: Python Flask
- Database: Oracle SQL XE 21c
- Frontend: HTML, CSS, JavaScript

## Features
- Student portal — search books, request borrows, track fines
- Staff portal — manage catalog, approve requests, issue/return books
- Automatic fine calculation (Rs.2/day overdue)
- Role-based access control

## Setup
1. Install dependencies: pip install -r requirements.txt
2. Create a .env file with your DB credentials
3. Run: py app.py