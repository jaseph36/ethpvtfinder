# setup.py
from setuptools import setup, find_packages

setup(
    name='ethpvtfinder',
    version='1.0.0',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'requests',
        'beautifulsoup4',
        'pyyaml',
        'cryptography',
        'eth_utils',
    ],
    entry_points={
        'console_scripts': [
            'ethpvtfinder = ethpvtfinder.ethpvtfinder:main',
        ],
    },
    author='jaseph36',
    author_email='jaseph.github@gmail.comm,
    description='A tool to find Ethereum private keys from verified messages on Etherscan.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/jaseph36/Ethpvtfinder',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
)
