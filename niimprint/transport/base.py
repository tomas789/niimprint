"""Base transport class for Niimprint printers."""

import abc


class BaseTransport(metaclass=abc.ABCMeta):
    """Abstract base class for all transport implementations."""
    
    @abc.abstractmethod
    def read(self, length: int) -> bytes:
        """Read data from the transport.
        
        Args:
            length: Maximum number of bytes to read
            
        Returns:
            bytes: Data read from transport
        """
        raise NotImplementedError

    @abc.abstractmethod
    def write(self, data: bytes) -> int:
        """Write data to the transport.
        
        Args:
            data: Data to write
            
        Returns:
            int: Number of bytes written
        """
        raise NotImplementedError
