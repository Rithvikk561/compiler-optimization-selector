import os
import subprocess
import argparse
import sys

def generate_ir(source_file, output_dir):
    """
    Compiles a C source file to LLVM IR (.ll) using clang.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    filename = os.path.basename(source_file)
    name_without_ext = os.path.splitext(filename)[0]
    output_file = os.path.join(output_dir, f"{name_without_ext}.ll")

    # Command: clang -O0 -S -emit-llvm <source> -o <output>
    # -O0: No optimization (clean IR)
    # -S: Emit human-readable assembly (IR in this case)
    # -emit-llvm: Generate LLVM IR
    # -w: Suppress all warnings (to keep output clean for students/demonstration)
    command = [
        r"C:\Program Files\LLVM\bin\clang.exe",
        "-O0",
        "-S",
        "-emit-llvm",
        "-w", 
        source_file,
        "-o",
        output_file
    ]

    print(f"Compiling {filename} -> {os.path.basename(output_file)}...")
    try:
        subprocess.run(command, check=True)
        print("Success!")
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"Error compiling {filename}: {e}")
        return None
    except FileNotFoundError:
        print("Error: 'clang' not found. Please ensure LLVM is installed and added to PATH.")
        return None

def main():
    parser = argparse.ArgumentParser(description="Compiler Frontend: Generate LLVM IR from C source.")
    parser.add_argument("--src", default="test_cases", help="Directory containing source files")
    parser.add_argument("--out", default="ir_output", help="Directory to save generated IR")
    args = parser.parse_args()

    source_dir = os.path.abspath(args.src)
    output_dir = os.path.abspath(args.out)

    if not os.path.exists(source_dir):
        print(f"Source directory not found: {source_dir}")
        print("Please run 'generate_tests.py' first to create test cases.")
        return

    print(f"Scanning {source_dir} for .c files...")
    count: int = 0
    success_count: int = 0
    
    # Ensure output directory exists from the start
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".c"):
                full_path = os.path.join(root, file)
                result = generate_ir(full_path, output_dir)
                count = count + 1
                if result is not None:
                    success_count = success_count + 1
    
    if count == 0:
        print("No .c files found to compile.")
    else:
        print(f"\nProcessing complete. {success_count}/{count} files compiled successfully.")
        print(f"IR files are located in: {output_dir}")

if __name__ == "__main__":
    main()
