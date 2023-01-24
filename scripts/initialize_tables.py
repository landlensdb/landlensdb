import argparse

from src.initializer import InitializeMapillary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Creates mly_images table if it doesnt exist already."
    )
    initializer = InitializeMapillary()
    initializer.create_image_table()
    initializer.create_snapped_geometries_table()
