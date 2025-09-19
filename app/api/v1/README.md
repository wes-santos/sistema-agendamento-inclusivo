# API v1

This directory contains the version 1 of the API endpoints for the inclusive scheduling system.

## Structure

The API is organized by domain entities:

- `auth.py` - Authentication endpoints
- `appointments_wizard.py` - Appointment scheduling wizard
- `availability.py` - Professional availability management
- `dashboard_coordination.py` - Coordination dashboard endpoints
- `dashboard_family.py` - Family dashboard endpoints
- `dashboard_professional.py` - Professional dashboard endpoints
- `professionals.py` - Professional management
- `public_appointments.py` - Public appointment endpoints (confirmation/cancellation)
- `slots.py` - Slot availability
- `students.py` - Student management

## Versioning

All endpoints in this directory are accessible under the `/api/v1` prefix.

## Migration

The previous flat structure in `/app/api/routes` has been moved to this versioned structure to allow for future API evolution while maintaining backward compatibility.