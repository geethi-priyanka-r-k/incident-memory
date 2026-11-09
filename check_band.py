import inspect
from band.core import AgentToolsProtocol

print(inspect.signature(AgentToolsProtocol.send_message))
print(inspect.getdoc(AgentToolsProtocol.send_message))