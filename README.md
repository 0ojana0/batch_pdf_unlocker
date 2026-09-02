# batch_pdf_unlocker
Removes owner restrictions (permissions lock) and decrypts user passwords for multiple PDF files.

## Features:
- Automatic removal of Owner Passwords / Permissions locks (printing, copying, editing restrictions).
- Batch processing of entire directories (with optional recursive scanning).
- Multi-threading support for rapid processing of large batches.
- Command Line Interface (CLI) and built-in Tkinter Graphical User Interface (GUI).
- Fallback support across `pikepdf` and `pypdf` libraries.

## Dependencies:
    pip install pikepdf
    (Optional fallback: pip install pypdf)
