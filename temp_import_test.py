import sys
import os
import pkgutil

# Add the parent directory of 'src' to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

try:
    import rufus
    print("Successfully imported rufus package!")
    print("rufus path:", rufus.__path__)

    # Try to import submodules
    try:
        from rufus import workflow
        print("Successfully imported rufus.workflow!")
    except ImportError as e:
        print(f"ImportError for rufus.workflow: {e}")

    try:
        from rufus import engine
        print("Successfully imported rufus.engine!")
    except ImportError as e:
        print(f"ImportError for rufus.engine: {e}")
        
    try:
        from rufus import builder
        print("Successfully imported rufus.builder!")
    except ImportError as e:
        print(f"ImportError for rufus.builder: {e}")

    # List contents of rufus package
    print("\nContents of rufus package:")
    for importer, modname, ispkg in pkgutil.iter_modules(rufus.__path__):
        print(f"  - {modname} (is_package: {ispkg})")

except ImportError as e:
    print(f"ImportError for rufus package: {e}")
    print("sys.path:", sys.path)
    print("Current working directory:", os.getcwd())
except Exception as e:
    print(f"An unexpected error occurred: {e}")