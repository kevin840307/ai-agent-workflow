from pathlib import Path
import sys
root=Path(__file__).parent; sys.path.insert(0,str(root))
from todo_service import TodoService
service=TodoService(); first=service.add("A"); second=service.add("B")
assert first.id==1 and second.id==2
assert service.complete(1).completed is True
assert [item.title for item in service.list_all()]==["A","B"]
assert (root/"models.py").is_file() and (root/"tests"/"test_todo_service.py").is_file()
print("PASS")
