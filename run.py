import uvicorn

if __name__ == "__main__":
    uvicorn.run("cero.api:app", host="127.0.0.1", port=8765, reload=False)
