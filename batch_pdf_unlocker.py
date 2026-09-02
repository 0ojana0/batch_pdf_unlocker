#!/usr/bin/env python3
"""
Batch PDF Unlocker Script
-------------------------
Removes owner restrictions (permissions lock) and decrypts user passwords for multiple PDF files.

Features:
- Automatic removal of Owner Passwords / Permissions locks (printing, copying, editing restrictions).
- Batch processing of entire directories (with optional recursive scanning).
- Multi-threading support for rapid processing of large batches.
- Command Line Interface (CLI) and built-in Tkinter Graphical User Interface (GUI).
- Fallback support across `pikepdf` and `pypdf` libraries.

Dependencies:
    pip install pikepdf
    (Optional fallback: pip install pypdf)
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional, Dict, Any

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("PDFUnlocker")

# Attempt primary and secondary library imports
PIKEPDF_AVAILABLE = False
PYPDF_AVAILABLE = False

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except ImportError:
    pass

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    pass


def unlock_single_pdf(
    input_path: Path, 
    output_path: Path, 
    passwords: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Attempts to unlock a single PDF file and save the unencrypted version to output_path.
    
    Returns:
        Dict with status info: {'status': 'success'|'skipped'|'failed', 'message': str, 'file': str}
    """
    if passwords is None:
        passwords = [""]
    elif "" not in passwords:
        passwords.insert(0, "") # Always try empty password first

    result = {
        "file": input_path.name,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "status": "failed",
        "message": ""
    }

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Primary Engine: pikepdf
    if PIKEPDF_AVAILABLE:
        return _unlock_with_pikepdf(input_path, output_path, passwords, result)
    
    # 2. Secondary Engine: pypdf fallback
    elif PYPDF_AVAILABLE:
        return _unlock_with_pypdf(input_path, output_path, passwords, result)
    
    else:
        result["message"] = "Neither 'pikepdf' nor 'pypdf' is installed. Run: pip install pikepdf"
        return result


def _unlock_with_pikepdf(
    input_path: Path, 
    output_path: Path, 
    passwords: List[str], 
    result: Dict[str, Any]
) -> Dict[str, Any]:
    """Unlocks PDF using pikepdf library."""
    pdf = None
    unlocked = False
    used_pwd = ""

    for pwd in passwords:
        try:
            # pikepdf automatically handles owner passwords even without supplying one
            pdf = pikepdf.open(input_path, password=pwd, allow_overwriting_input=True)
            unlocked = True
            used_pwd = pwd
            break
        except pikepdf.PasswordError:
            continue
        except pikepdf.PdfError as e:
            result["message"] = f"PDF structure error: {str(e)}"
            return result
        except Exception as e:
            result["message"] = f"Unexpected error: {str(e)}"
            return result

    if unlocked and pdf is not None:
        try:
            # Save unencrypted PDF
            pdf.save(output_path)
            pdf.close()
            result["status"] = "success"
            if used_pwd:
                result["message"] = f"Unlocked using password: '{used_pwd}'"
            else:
                result["message"] = "Unlocked (No password / Owner restriction removed)"
        except Exception as e:
            result["message"] = f"Failed to save unlocked file: {str(e)}"
    else:
        result["message"] = "Password required (or none of the provided passwords matched)."

    return result


def _unlock_with_pypdf(
    input_path: Path, 
    output_path: Path, 
    passwords: List[str], 
    result: Dict[str, Any]
) -> Dict[str, Any]:
    """Fallback PDF unlocker using pypdf library."""
    try:
        reader = pypdf.PdfReader(input_path)
        
        if reader.is_encrypted:
            unlocked = False
            for pwd in passwords:
                try:
                    if reader.decrypt(pwd) > 0:
                        unlocked = True
                        break
                except Exception:
                    continue
            
            if not unlocked:
                result["message"] = "Password required or invalid password list."
                return result

        writer = pypdf.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
            
        with open(output_path, "wb") as f_out:
            writer.write(f_out)

        result["status"] = "success"
        result["message"] = "Unlocked successfully via pypdf fallback."
    except Exception as e:
        result["message"] = f"pypdf error: {str(e)}"

    return result


class BatchPDFUnlocker:
    """Manages batch unlocking operations over directories or file lists."""
    
    def __init__(
        self, 
        input_dir: str, 
        output_dir: str, 
        passwords: Optional[List[str]] = None,
        recursive: bool = False,
        max_workers: int = 4
    ):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.passwords = passwords or []
        self.recursive = recursive
        self.max_workers = max_workers

    def discover_files(self) -> List[Path]:
        """Scans input directory for PDF files."""
        if not self.input_dir.exists():
            logger.error(f"Input directory does not exist: {self.input_dir}")
            return []

        pattern = "**/*.pdf" if self.recursive else "*.pdf"
        files = [p for p in self.input_dir.glob(pattern) if p.is_file()]
        return sorted(files)

    def process_all(self, progress_callback=None) -> Dict[str, Any]:
        """Executes unlock tasks across all discovered PDF files."""
        files = self.discover_files()
        total_files = len(files)
        
        if total_files == 0:
            logger.warning("No PDF files found to process.")
            return {"total": 0, "success": 0, "failed": 0, "details": []}

        logger.info(f"Starting batch unlock for {total_files} PDF files...")
        results = []
        success_count = 0
        failed_count = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {}
            for file_path in files:
                # Retain relative directory structure for recursive mode
                if self.recursive:
                    rel_path = file_path.relative_to(self.input_dir)
                    dest_path = self.output_dir / rel_path
                else:
                    dest_path = self.output_dir / file_path.name
                
                # Append '_unlocked' suffix if target is in the same directory
                if dest_path.resolve() == file_path.resolve():
                    dest_path = dest_path.with_name(f"{file_path.stem}_unlocked.pdf")

                future = executor.submit(unlock_single_pdf, file_path, dest_path, self.passwords)
                future_to_file[future] = file_path

            completed = 0
            for future in as_completed(future_to_file):
                res = future.result()
                results.append(res)
                completed += 1

                if res["status"] == "success":
                    success_count += 1
                    logger.info(f"[{completed}/{total_files}] SUCCESS: {res['file']} -> {res['message']}")
                else:
                    failed_count += 1
                    logger.error(f"[{completed}/{total_files}] FAILED: {res['file']} -> {res['message']}")

                if progress_callback:
                    progress_callback(completed, total_files, res)

        summary = {
            "total": total_files,
            "success": success_count,
            "failed": failed_count,
            "details": results
        }
        
        logger.info(f"Batch processing complete! Success: {success_count}/{total_files}, Failed: {failed_count}")
        return summary


def launch_gui():
    """Launches desktop Tkinter GUI application."""
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        logger.error("Tkinter module is not available on this Python installation.")
        sys.exit(1)

    class PDFUnlockerApp:
        def __init__(self, root):
            self.root = root
            self.root.title("Batch PDF Unlocker")
            self.root.geometry("640x520")
            self.root.minsize(550, 450)

            # Theme & Styles
            style = ttk.Style()
            style.theme_use('clam')

            # Main container
            padding = {'padx': 10, 'pady': 5}

            # Input Folder Selection
            frame_input = ttk.LabelFrame(root, text="Source PDF Directory", padding=10)
            frame_input.pack(fill="x", padx=10, pady=5)

            self.input_var = tk.StringVar()
            ttk.Entry(frame_input, textvariable=self.input_var).pack(side="left", fill="x", expand=True, padx=(0, 5))
            ttk.Button(frame_input, text="Browse...", command=self.browse_input).pack(side="right")

            # Output Folder Selection
            frame_output = ttk.LabelFrame(root, text="Output Directory", padding=10)
            frame_output.pack(fill="x", padx=10, pady=5)

            self.output_var = tk.StringVar()
            ttk.Entry(frame_output, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=(0, 5))
            ttk.Button(frame_output, text="Browse...", command=self.browse_output).pack(side="right")

            # Options Frame
            frame_options = ttk.LabelFrame(root, text="Options & Passwords", padding=10)
            frame_options.pack(fill="x", padx=10, pady=5)

            self.recursive_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(frame_options, text="Include Subfolders (Recursive)", variable=self.recursive_var).pack(anchor="w")

            ttk.Label(frame_options, text="User Passwords (one per line, optional):").pack(anchor="w", pady=(5, 2))
            self.txt_passwords = tk.Text(frame_options, height=3, width=40)
            self.txt_passwords.pack(fill="x", expand=True)

            # Progress Bar & Status
            frame_progress = ttk.Frame(root, padding=10)
            frame_progress.pack(fill="x", padx=10)

            self.progress_bar = ttk.Progressbar(frame_progress, mode="determinate")
            self.progress_bar.pack(fill="x", pady=2)

            self.lbl_status = ttk.Label(frame_progress, text="Ready", font=("Helvetica", 9, "italic"))
            self.lbl_status.pack(anchor="w")

            # Action Button
            self.btn_run = ttk.Button(root, text="Start Unlocking PDFs", command=self.run_batch)
            self.btn_run.pack(pady=10)

            # Log Window
            frame_log = ttk.LabelFrame(root, text="Activity Log", padding=10)
            frame_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

            self.txt_log = tk.Text(frame_log, height=8, state="disabled", wrap="word")
            self.txt_log.pack(fill="both", expand=True)

        def browse_input(self):
            path = filedialog.askdirectory(title="Select Source Folder with PDFs")
            if path:
                self.input_var.set(path)
                if not self.output_var.get():
                    self.output_var.set(str(Path(path) / "unlocked"))

        def browse_output(self):
            path = filedialog.askdirectory(title="Select Output Directory")
            if path:
                self.output_var.set(path)

        def log_message(self, msg: str):
            self.txt_log.config(state="normal")
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")

        def run_batch(self):
            input_dir = self.input_var.get().strip()
            output_dir = self.output_var.get().strip()

            if not input_dir or not os.path.isdir(input_dir):
                messagebox.showerror("Error", "Please select a valid source directory.")
                return

            if not output_dir:
                messagebox.showerror("Error", "Please select a valid output directory.")
                return

            raw_passwords = self.txt_passwords.get("1.0", "end").splitlines()
            passwords = [p.strip() for p in raw_passwords if p.strip()]

            self.btn_run.config(state="disabled")
            self.progress_bar["value"] = 0
            self.lbl_status.config(text="Processing...")
            self.txt_log.config(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.config(state="disabled")

            def progress_update(completed, total, res):
                self.progress_bar["maximum"] = total
                self.progress_bar["value"] = completed
                self.lbl_status.config(text=f"Processed {completed} of {total} files...")
                tag = "SUCCESS" if res["status"] == "success" else "FAILED"
                self.log_message(f"[{tag}] {res['file']}: {res['message']}")

            def task():
                unlocker = BatchPDFUnlocker(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    passwords=passwords,
                    recursive=self.recursive_var.get()
                )
                summary = unlocker.process_all(progress_callback=progress_update)
                
                self.root.after(0, lambda: self.finish_batch(summary))

            import threading
            threading.Thread(target=task, daemon=True).start()

        def finish_batch(self, summary):
            self.btn_run.config(state="normal")
            self.lbl_status.config(text="Batch complete!")
            messagebox.showinfo(
                "Completed", 
                f"Batch process finished!\n\nTotal: {summary['total']}\nSuccess: {summary['success']}\nFailed: {summary['failed']}"
            )

    root = tk.Tk()
    app = PDFUnlockerApp(root)
    root.mainloop()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Batch unlock PDFs (remove owner permissions lock and decrypt user passwords)."
    )
    parser.add_argument("-i", "--input", help="Source folder containing PDF files")
    parser.add_argument("-o", "--output", help="Destination folder for unlocked PDFs")
    parser.add_argument("-p", "--password", action="append", help="Candidate password(s) to try (can specify multiple -p args)")
    parser.add_argument("-f", "--password-file", help="Path to a text file containing passwords (one per line)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively scan subfolders")
    parser.add_argument("-t", "--threads", type=int, default=4, help="Number of concurrent worker threads (default: 4)")
    parser.add_argument("--gui", action="store_true", help="Launch Graphical User Interface")

    args = parser.parse_args()

    # Check dependencies
    if not PIKEPDF_AVAILABLE and not PYPDF_AVAILABLE:
        print("\n[ERROR] Required PDF library not found!")
        print("Please install pikepdf by running:\n    pip install pikepdf\n")
        sys.exit(1)

    # Launch GUI if explicit or no args passed
    if args.gui or len(sys.argv) == 1:
        launch_gui()
        return

    if not args.input:
        parser.error("The --input (-i) argument is required when running in CLI mode.")

    output_dir = args.output or os.path.join(args.input, "unlocked")

    # Collect passwords
    passwords = args.password or []
    if args.password_file and os.path.exists(args.password_file):
        with open(args.password_file, "r", encoding="utf-8", errors="ignore") as f:
            passwords.extend([line.strip() for line in f if line.strip()])

    # Run CLI unlocker
    unlocker = BatchPDFUnlocker(
        input_dir=args.input,
        output_dir=output_dir,
        passwords=passwords,
        recursive=args.recursive,
        max_workers=args.threads
    )

    summary = unlocker.process_all()
    print(f"\n--- Batch Summary ---")
    print(f"Total PDFs found: {summary['total']}")
    print(f"Successfully Unlocked: {summary['success']}")
    print(f"Failed / Shielded: {summary['failed']}")


if __name__ == "__main__":
    main()