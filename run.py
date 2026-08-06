import multiprocessing

multiprocessing.freeze_support()

import uvicorn


if __name__ == '__main__':
    uvicorn.run('app:app', host='0.0.0.0', port=8000, workers=1)
