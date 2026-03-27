"""
Todos API module.
Wraps all /api/todos endpoints — add new methods here as the Laravel API grows.
"""
from app.api.client import get_client


def get_todos(completed: bool = None, page: int = 1) -> dict:
    params = {'page': page}
    if completed is not None:
        params['completed'] = int(completed)
    return get_client().get('/todos', params=params)


def get_todo(todo_id: int) -> dict:
    return get_client().get(f'/todos/{todo_id}')


def create_todo(todo: str, completed_at: str = None) -> dict:
    payload = {'todo': todo}
    if completed_at:
        payload['completed_at'] = completed_at
    return get_client().post('/todos', json=payload)


def complete_todo(todo_id: int) -> dict:
    return get_client().put(f'/todos/{todo_id}/complete')


def update_todo(todo_id: int, todo: str = None, completed: bool = None,
                completed_at: str = None) -> dict:
    payload = {}
    if todo is not None:
        payload['todo'] = todo
    if completed is not None:
        payload['completed'] = completed
    if completed_at is not None:
        payload['completed_at'] = completed_at
    return get_client().put(f'/todos/{todo_id}', json=payload)


def delete_todo(todo_id: int) -> dict:
    return get_client().delete(f'/todos/{todo_id}')


def get_history(from_date: str = None, to_date: str = None, page: int = 1) -> dict:
    params = {'page': page}
    if from_date:
        params['from'] = from_date
    if to_date:
        params['to'] = to_date
    return get_client().get('/todos/history', params=params)
