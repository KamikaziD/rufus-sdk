from fastapi import APIRouter, HTTPException
from old.services.redis_service import redis_service

router = APIRouter()

@router.get("/")
async def get_history():
    """Get conversation history"""
    try:
        keys = await redis_service.keys("history:*")
        history = []
        
        for key in keys:
            session = await redis_service.get(key)
            if session:
                history.append(session)
        
        # Sort by timestamp descending
        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return {"history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get specific session"""
    try:
        session = await redis_service.get(f"history:{session_id}")
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    try:
        success = await redis_service.delete(f"history:{session_id}")
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/")
async def clear_history():
    """Clear all history"""
    try:
        keys = await redis_service.keys("history:*")
        for key in keys:
            await redis_service.delete(key)
        return {"success": True, "deleted": len(keys)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
