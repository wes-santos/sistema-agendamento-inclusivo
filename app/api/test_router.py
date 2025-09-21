from fastapi import APIRouter

test_router = APIRouter(prefix="/test", tags=["test"])

@test_router.get("/hello")
def hello():
    return {"message": "Hello from test router!"}