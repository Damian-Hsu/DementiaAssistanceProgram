
# [System Rule: Development Documentation Protocol]

## 📚 Required Pre-Reading

Before executing **any development task**, the agent **MUST**:

1. **Read and analyze the following documents in order**:
   - `design/spec.md` — Technical specifications and system architecture  
   - `design/report.md` — Development progress and historical decisions  
   - `design/todolist.md` — Current tasks and priorities  
   - `design/development_manual.md` — Development environment and workflows  

2. **Extract and understand**:
   - Current project context and goals  
   - Technical architecture and design decisions  
   - Completed features and current progress  
   - Pending tasks and their priorities  
   - Development environment setup  
   - Known issues and their solutions  

3. **Before starting any task**:
   - Confirm understanding of the project state  
   - Identify which files need to be modified  
   - Check for potential conflicts with existing code  
   - Verify that the task aligns with project goals  

---

## ⚠️ Exceptions

- `README.md` is **excluded** from mandatory pre-reading (only read when specifically relevant).  
- The user may explicitly request to skip pre-reading by stating **"skip pre-reading"**.  

---

## 🚫 Never Do

- Start coding without understanding the project context.  
- Make changes that conflict with existing architecture.  
- Ignore documented patterns and conventions.  
- Skip reading documentation even for “simple” tasks.  

---

## ✅ Always Do

- Read all required documents before proposing solutions.  
- Reference specific sections from documentation when explaining decisions.  
- Update relevant documentation after completing tasks.  
- Maintain consistency with established patterns.  

---

# [System Rule: Task Summary Handling]

## 🧾 Task Summary Policy

### 🚫 Prohibited Behavior

- The agent **MUST NOT** generate or output standalone summaries of completed tasks in chat responses.  
- The agent **MUST NOT** produce post-task overviews or conclusions outside of documentation files.  
- Any synthesized summaries, reflections, or completion notes **must not appear** in console/chat output.  

---

### 🧭 Required Behavior

After completing a task, the agent **MUST**:

1. Append a concise, factual task summary **directly to** `design/report.md`, under the appropriate section (e.g. `## Task Reports` or `## Progress Logs`).  
2. Include the following information:
   - Task name or ID  
   - Date and time of completion  
   - Description of changes made  
   - Related modules/files affected  
   - Outcome or resolution (e.g., “Bug fixed”, “API updated”, “Function refactored”)  
3. Maintain chronological order (most recent updates at the top or in the latest section).  
4. Use **technical, objective writing style** — no redundant or conversational tone.  

---

### 🧱 Example Format (for `report.md`)

```markdown
## [2025-10-20] Task Update: 修復 API 查詢影片列表資料格式錯誤
- **Files Updated:** /api/video_list.py, /utils/time_parser.py  
- **Issue:** "duration", "start_time", "end_time" returned null  
- **Cause:** Improper null-handling in serializer  
- **Resolution:** Added default value fallback and validation logic  
- **Status:** Fixed  
````

---

### 🧩 Integration Rule

* This rule extends the **Development Documentation Protocol** and inherits its pre-reading requirements.
* The agent must ensure the `report.md` file is **loaded, parsed, and updated** during the post-task phase.
* If `report.md` is missing, the agent should **request user permission** before creating a new one.

---

[End of System Rule]