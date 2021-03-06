# -*- coding: utf-8 -*-

# We may import this during setup invocation
# because of the version we have to query
# However, i.e. numpy may not be installed at setup install time.
try:
    from imreg_dft.imreg import *
except ImportError as exc:
    print("Unable to import the main package: %s" % exc.message)


__version__ = "1.0.5-pre"
