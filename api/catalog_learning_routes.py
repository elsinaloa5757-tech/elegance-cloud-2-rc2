from fastapi import APIRouter, HTTPException
from services.catalog_learning_engine import migrate, stats, job, enqueue, resume_pending

router=APIRouter()

@router.get("/api/catalog-learning/stats")
def learning_stats():
    migrate()
    return stats()

@router.get("/api/catalog-learning/job/{job_id}")
def learning_job(job_id:str):
    try:return job(job_id)
    except Exception as e:raise HTTPException(status_code=404,detail=str(e))

@router.post("/api/catalog-learning/learn/{product_id}")
def learn(product_id:str):
    try:return enqueue(product_id)
    except Exception as e:raise HTTPException(status_code=400,detail=str(e))

@router.post("/api/catalog-learning/resume")
def resume():
    return {"status":"ok","resumed":resume_pending()}
