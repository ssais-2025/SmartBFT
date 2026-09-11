# Byzantine Fault-Tolerant Replicated State Machine Library



This is a Byzantine fault-tolerant (BFT) state machine replication (SMR) library. 
It is an open source library written in Go.
The implementation is inspired by the [BFT-SMaRt project](https://github.com/bft-smart/library). 
For more information on this library see our [wiki page](https://github.com/hyperledger-labs/SmartBFT/wiki).

## MWVN regional-consensus demo

This fork includes a standalone browser demo with four Python regional cores paired with four independent SmartBFT engine processes, a synthetic approved-QC form, consensus-message tracing, and per-validator ledger inspection.

See the [MWVN demo user guide](deploy/local/README.md) for prerequisites, installation, running, testing, and limitations.


## License

The source code files are made available under the Apache License, Version 2.0 (Apache-2.0), located in the [LICENSE](LICENSE) file.


## Contact

* Yacov Manevich - [yacovm@il.ibm.com](mailto:yacovm@il.ibm.com)
* Hagar Meir - [hagar.meir@ibm.com](mailto:hagar.meir@ibm.com)
* Artem Barger - [bartem@il.ibm.com](mailto:bartem@il.ibm.com)
* Yoav Tock - [tock@il.ibm.com](mailto:tock@il.ibm.com)
