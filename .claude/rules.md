# Coding Rules and Standards

## Critical Rules
1. NO EMOJIS - Use text-based indicators only
2. NO HARDCODING - Use environment variables and configuration
3. COMPREHENSIVE LOGGING - Log all important operations
4. GRACEFUL ERROR HANDLING - All external calls must have try-except
5. NO PARTIAL IMPLEMENTATIONS - Fully implement or document clearly
6. PROPER LOGGING SETUP - Use standardized logging configuration
7. CLEAN CODE STRUCTURE - Follow project organization
8. TEXT READABILITY - All UI text must be readable with high contrast
9. LOAD ENV VARIABLES LOCALLY - always use local .env file at root to laod any variable
10. NO TESTTING or COMMITS required from your end - USER will do so, NOT YOU

## WARNING

- You are not a tester. You should never test out features unless explicitly asked to
- NO MD FILES - do not create summary files or elsewise unless explicitly told to. You are free to summarize what you did in responce, just not in extra files

## UI/UX Readability Rules
1. **Text Color Contrast**
   - Main text: Use gray-800 or darker on light backgrounds
   - Never use light gray (gray-300/400) for body text
   - Placeholder text: gray-500 minimum
   - Ensure WCAG AA compliance (4.5:1 contrast ratio minimum)

2. **Input Fields**
   - Input text: text-gray-900 (dark text)
   - Placeholder: placeholder:text-gray-500 or darker
   - Never rely on default browser gray which is too light

3. **Code/Inline Elements**
   - Code snippets: text-gray-800 with bg-gray-100 or bg-white
   - Inline code: High contrast on any background

4. **Labels and Headers**
   - Labels: text-gray-800 or text-gray-900
   - Helper text: text-gray-700 minimum (never gray-600 or lighter for important info)

5. **Example of Good Contrast**
   ```tsx
   // Good - Readable
   <p className="text-gray-800">Main text</p>
   <input className="text-gray-900 placeholder:text-gray-500" />

   // Bad - Too light
   <p className="text-gray-400">Main text</p>
   <input className="text-gray-500" />
   ```

## File Structure Rules
- Keep files in appropriate directories (models/, routes/, etc.)
- Use __init__.py files in Python packages
- Follow the defined project structure
- No ad-hoc file creation

## Error Handling Pattern
```python
try:
    # Operation
    result = external_call()
except SpecificException as e:
    logging.error(f"[MODULE] Specific error: {str(e)}", exc_info=True)
    # Handle gracefully
except Exception as e:
    logging.error(f"[MODULE] Unexpected error: {str(e)}", exc_info=True)
    # Maintain system stability
finally:
    # Always cleanup
```

## Logging Pattern
```python
logging.info("[CATEGORY] Action description")
logging.error("[CATEGORY] Error description: {error}")
```

## Configuration Management
- Use config.py for application settings
- Use .env for environment variables
- No hardcoded values in code