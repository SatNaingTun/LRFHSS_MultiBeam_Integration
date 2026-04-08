# 🚨 CODEX RULES (STRICT ENFORCEMENT)

## 0. PRIMARY DIRECTIVE

You MUST:
- Reuse existing code
- Never reimplement existing functionality
- Follow connector-based architecture

---

## 1. CORE PRINCIPLES

### core-dry
DO NOT duplicate logic.

Definition:
- One logic = one implementation
- Reuse everywhere else

Reason:
DRY ensures maintainability and avoids inconsistent bugs :contentReference[oaicite:0]{index=0}

---

### core-reuse-first
Before writing code:

SEARCH ORDER:
1. Local codebase
2. lrfhss_connector
3. multi_beam_connector
4. External repos (LR-FHSS / AGNES)

IF FOUND → reuse  
IF NOT → write minimal code  

---

### core-no-reimplementation (CRITICAL)

FORBIDDEN:
- Rewriting LR-FHSS demodulation
- Rewriting FHS generation
- Rewriting Early Decode / Early Drop
- Rewriting AGNES beam logic

Reason:
Do not reinvent the wheel :contentReference[oaicite:1]{index=1}

---

### core-kiss
Keep solutions simple.

- No unnecessary abstraction
- No overengineering

---

### core-yagni
Do not implement unused features.

---

## 2. ARCHITECTURE RULES

### arch-layered

STRICT separation:

```text
Main App
   ↓
Connectors (Adapters)
   ↓
External Code (LR-FHSS / AGNES)
```

## 10. FORMULA TRACEABILITY RULE (MANDATORY)

All calculations MUST include:

1. Mathematical formula
2. Source reference (paper / section / equation)
3. Variable definitions

---

### REQUIRED FORMAT

Every calculation MUST follow:

```python
# Formula:
#   <LaTeX or math form>
# Source:
#   <Paper name>, Section X, Eq.(Y)
# Variables:
#   a: description
#   b: description

result = ...
```