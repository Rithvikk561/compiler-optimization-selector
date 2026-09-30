import os
import re
import csv
import glob

def extract_features(ir_file_path):
    """
    Parses an LLVM IR file and extracts feature counts.
    """
    features = {
        'filename': os.path.basename(ir_file_path),
        'num_functions': 0,
        'num_branches': 0,
        'num_loops': 0, # Approximated by branches/switches for this level
        'num_calls': 0,
        'num_memory_ops': 0,
        'num_arithmetic_ops': 0
    }

    # Regex patterns for IR instructions
    # Note: These are simplified patterns.
    patterns = {
        'function_def': re.compile(r'^define\s+'),
        'branch': re.compile(r'\b(br|switch|indirectbr)\b'),
        'call': re.compile(r'\b(call|invoke)\b'),
        'memory': re.compile(r'\b(alloca|load|store|getelementptr|fence|cmpxchg|atomicrmw)\b'),
        'arithmetic': re.compile(r'\b(add|fadd|sub|fsub|mul|fmul|udiv|sdiv|fdiv|urem|srem|frem|shl|lshr|ashr|and|or|xor)\b')
    }

    try:
        with open(ir_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith(';'):
                    continue
                
                # Skip metadata and declarations
                if line.startswith(('source_filename', 'target', 'attributes', '!', 'declare')):
                    continue

                # Count Functions
                if patterns['function_def'].match(line):
                    features['num_functions'] += 1

                # Count Branches (Loops are often implemented with branches)
                if patterns['branch'].search(line):
                    features['num_branches'] += 1
                    # Rough heuristic: often loops involve a branch back. 
                    # For strict loop counting, we'd need a CFG, but we'll use branch count as a proxy for control flow complexity.
                    features['num_loops'] += 1 

                # Count Calls
                if patterns['call'].search(line):
                    features['num_calls'] += 1

                # Count Memory Operations
                if patterns['memory'].search(line):
                    features['num_memory_ops'] += 1

                # Count Arithmetic Operations
                if patterns['arithmetic'].search(line):
                    features['num_arithmetic_ops'] += 1

    except Exception as e:
        print(f"Error processing {ir_file_path}: {e}")
        return None

    return features

def main():
    # Directory containing IR files
    ir_dir = os.path.join(os.path.dirname(__file__), 'ir_output')
    output_csv = os.path.join(os.path.dirname(__file__), 'ir_features.csv')

    print(f"Searching for .ll files in {ir_dir}...")
    
    ir_files = glob.glob(os.path.join(ir_dir, '*.ll'))
    
    if not ir_files:
        print("No .ll files found in ir_output directory.")
        return

    print(f"Found {len(ir_files)} files. Extracting features...")

    extracted_data = []
    
    for ir_file in ir_files:
        data = extract_features(ir_file)
        if data:
            extracted_data.append(data)

    if extracted_data:
        # Write to CSV
        fieldnames = ['filename', 'num_functions', 'num_branches', 'num_loops', 'num_calls', 'num_memory_ops', 'num_arithmetic_ops']
        
        try:
            with open(output_csv, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(extracted_data)
            
            print(f"Successfully wrote features to {output_csv}")
            
            # Print sample output to console
            print("\nSample Extracted Features:")
            print(f"{'Filename':<25} | {'Funcs':<5} | {'Br/Loop':<7} | {'Calls':<5} | {'Mem':<5} | {'Arith':<5}")
            print("-" * 70)
            for row in extracted_data[:5]:
                print(f"{row['filename']:<25} | {row['num_functions']:<5} | {row['num_branches']:<7} | {row['num_calls']:<5} | {row['num_memory_ops']:<5} | {row['num_arithmetic_ops']:<5}")

        except Exception as e:
            print(f"Error writing CSV: {e}")
    else:
        print("No features extracted.")

if __name__ == "__main__":
    main()
