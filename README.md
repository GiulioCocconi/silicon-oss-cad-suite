# OSS CAD Suite

Fork of [YosysHQ OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build/) for [SILICON](https://github.com/GiulioCocconi/SILICON)

## Contributing

To be able to build OSS CAD Suite yourself, you need to install `docker` (please note this only works on x64 platforms or under rosetta on macos-arm) and `python 3.6` or higher, with the `click` library.


After that just running ```./builder.py``` should work fine.

To build default build:
```bash
./builder.py build 
```

To skip update of source code, you can always:
```bash
./builder.py build --no-update
```

To build specific target and architecture:
```bash
./builder.py build --target=yosys --arch=linux-arm64
```

## Alternatives

If your project is primarily written in Python (using tools such as Amaranth or LiteX), and you only need synthesis and PnR tools, you might find [YoWASP](https://yowasp.org) more suited to your needs since it allows managing installation and versioning of these tools in the same way as any other Python package dependencies.
