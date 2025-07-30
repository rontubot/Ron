import uvicorn

if __name__ == "__main__":
    print("🚀 Levantando servidor de Ron con FastAPI...")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
