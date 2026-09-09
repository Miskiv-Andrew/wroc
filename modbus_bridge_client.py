# modbus_bridge_client.py

import json
import socket
import threading
import time

from PySide6.QtCore import QObject, Signal


# ============================================================================
# Default connection parameters
#
# ModBusBridgeService listens on the local TCP interface.
# These values can be overridden when ModBusBridgeClient is created.
# ============================================================================
DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 12345


class ModBusBridgeClient(QObject):
    """
    ==========================================================================
    ModBusBridgeClient
    ==========================================================================

    Purpose
    -------
    This class provides a reliable TCP connection between the Python
    application and ModBusBridgeService.

    The class is completely independent from GUI widgets.

    Responsibilities
    ----------------
    1. Establish TCP connection with ModBusBridgeService.
    2. Maintain the connection.
    3. Automatically reconnect after unexpected connection loss.
    4. Send JSON messages terminated by '\n'.
    5. Receive newline-delimited JSON messages.
    6. Correctly handle fragmented TCP packets.
    7. Correctly handle several JSON messages received in one TCP packet.
    8. Protect socket operations from concurrent access.
    9. Detect malformed or excessively large incoming messages.
    10. Perform controlled shutdown without leaving reader/reconnect threads.

    Protocol
    --------
    Messages are encoded as UTF-8 JSON and terminated by one newline byte:

        JSON + '\n'

    Important
    ---------
    This class does NOT know anything about:

    - GUI;
    - Modbus registers;
    - PLC addresses;
    - isotope identification logic;
    - device polling logic;
    - database logic.

    It only transports prepared application data to ModBusBridgeService
    and delivers received JSON objects back to the application.
    """

    # ------------------------------------------------------------------------
    # Public signals
    # ------------------------------------------------------------------------

    # Emitted once when TCP connection has been successfully established.
    connected = Signal()

    # Emitted once when an existing TCP connection has been lost or closed.
    disconnected = Signal()

    # Emitted for every correctly decoded incoming JSON object.
    dataReceived = Signal(dict)

    # Emitted when a communication or protocol error occurs.
    errorOccurred = Signal(str)

    # Diagnostic messages for GUI log, console log or file logger.
    logMessage = Signal(str)

    # =========================================================================
    # ModBusBridgeClient.__init__
    #
    # Creates the client object but does not immediately connect.
    #
    # host:
    #     IP address of ModBusBridgeService.
    #
    # port:
    #     TCP port of ModBusBridgeService.
    #
    # reconnect_interval:
    #     Delay between automatic reconnect attempts, in seconds.
    # =========================================================================
    def __init__(
        self,
        host=DEFAULT_BRIDGE_HOST,
        port=DEFAULT_BRIDGE_PORT,
        reconnect_interval=3.0,
        parent=None
    ):
        super().__init__(parent)

        self.host = host
        self.port = port

        # Delay between reconnect attempts.
        self.reconnect_interval = reconnect_interval

        # Connection timeout prevents connect() from hanging indefinitely.
        self.connect_timeout = 3.0

        # recv() timeout is intentionally short.
        #
        # The timeout allows the reader thread to periodically check whether
        # shutdown was requested.
        self.receive_timeout = 1.0

        # Maximum size of one incoming JSON frame.
        #
        # ModBusBridgeService uses relatively small JSON messages, therefore
        # 64 KiB is more than sufficient and protects against uncontrolled
        # memory growth if the protocol stream becomes corrupted.
        self.max_message_size = 64 * 1024

        # Current socket object.
        self._socket = None

        # Protects socket creation, replacement and closing.
        self._socket_lock = threading.RLock()

        # Protects send operations.
        #
        # Without this lock two application threads could call sendall()
        # simultaneously and mix two JSON messages in the TCP stream.
        self._send_lock = threading.Lock()

        # Signals all worker threads that the object is shutting down.
        self._stop_event = threading.Event()

        # Signals that automatic reconnect work is required.
        self._reconnect_event = threading.Event()

        # Reader thread for the currently active socket.
        self._reader_thread = None

        # One persistent reconnect worker.
        self._reconnect_thread = None

        # Protects internal connection state.
        self._state_lock = threading.Lock()

        # True only while a valid TCP connection is active.
        self._connected = False

        # True after explicit disconnect()/shutdown().
        #
        # Automatic reconnect is allowed only while this value is False.
        self._manual_disconnect = False

        # Prevents duplicate disconnected signals.
        self._disconnected_signal_sent = True

    # =========================================================================
    # ModBusBridgeClient.is_connected
    #
    # Returns True only when the client currently considers the TCP connection
    # active.
    # =========================================================================
    def is_connected(self):
        with self._state_lock:
            return self._connected

    # =========================================================================
    # ModBusBridgeClient.connect_to_bridge
    #
    # Starts connection to ModBusBridgeService.
    #
    # The first connection attempt is synchronous so the caller immediately
    # knows whether the Bridge is currently available.
    #
    # If the first attempt fails, the reconnect worker continues trying in the
    # background.
    #
    # Returns:
    #     True  - connected immediately;
    #     False - first attempt failed, reconnect will continue automatically.
    # =========================================================================
    def connect_to_bridge(self):
        self._manual_disconnect = False
        self._stop_event.clear()

        self._ensure_reconnect_thread()

        if self.is_connected():
            return True

        if self._open_connection():
            return True

        # Initial connection failed.
        # Ask the reconnect worker to continue attempts in background.
        self._reconnect_event.set()

        return False

    # =========================================================================
    # ModBusBridgeClient.disconnect
    #
    # Performs an intentional disconnect.
    #
    # Automatic reconnect is disabled until connect_to_bridge() is called
    # again.
    # =========================================================================
    def disconnect(self):
        self._manual_disconnect = True

        # Stop reconnect attempts.
        self._reconnect_event.clear()

        self._close_current_socket(
            emit_disconnected=True,
            reason="Disconnected from ModBusBridgeService"
        )

    # =========================================================================
    # ModBusBridgeClient.shutdown
    #
    # Completely stops the communication object.
    #
    # This method must be called when the application is closing.
    #
    # It:
    # - disables reconnect;
    # - requests worker threads to stop;
    # - closes the socket;
    # - waits briefly for worker threads.
    #
    # The method is safe to call more than once.
    # =========================================================================
    def shutdown(self):
        self._manual_disconnect = True

        self._stop_event.set()
        self._reconnect_event.set()

        self._close_current_socket(
            emit_disconnected=True,
            reason="ModBusBridgeClient stopped"
        )

        current_thread = threading.current_thread()

        reader_thread = self._reader_thread

        if (
            reader_thread is not None
            and reader_thread.is_alive()
            and reader_thread is not current_thread
        ):
            reader_thread.join(timeout=2.0)

        reconnect_thread = self._reconnect_thread

        if (
            reconnect_thread is not None
            and reconnect_thread.is_alive()
            and reconnect_thread is not current_thread
        ):
            reconnect_thread.join(timeout=2.0)

    # =========================================================================
    # ModBusBridgeClient.send_data
    #
    # Sends one arbitrary JSON object to ModBusBridgeService.
    #
    # The method preserves the protocol already tested in the previous Python
    # application:
    #
    #     JSON + newline
    #
    # sendall() is used instead of send() so Python continues writing until the
    # entire encoded message has been accepted by the socket or an error occurs.
    #
    # Returns:
    #     True  - complete message was accepted for transmission;
    #     False - connection is unavailable or communication failed.
    # =========================================================================
    def send_data(self, data):
        if not isinstance(data, dict):
            self._report_error(
                "Cannot send data: top-level message must be a dictionary"
            )
            return False

        try:
            message = (
                json.dumps(
                    data,
                    ensure_ascii=False,
                    separators=(",", ":")
                )
                + "\n"
            )

            encoded_message = message.encode("utf-8")

        except (TypeError, ValueError) as exc:
            self._report_error(
                f"Cannot serialize JSON message: {exc}"
            )
            return False

        if len(encoded_message) > self.max_message_size:
            self._report_error(
                "Cannot send data: JSON message exceeds maximum allowed size"
            )
            return False

        with self._send_lock:

            with self._socket_lock:
                current_socket = self._socket

            if current_socket is None or not self.is_connected():
                self._report_error(
                    "Cannot send data: ModBusBridgeService is not connected"
                )

                self._request_reconnect()
                return False

            try:
                current_socket.sendall(encoded_message)

                self.logMessage.emit(
                    f"Sent {len(encoded_message)} bytes to ModBusBridgeService"
                )

                return True

            except (OSError, socket.error) as exc:
                self._handle_connection_failure(
                    f"Send error: {exc}",
                    failed_socket=current_socket
                )

                return False

    # =========================================================================
    # ModBusBridgeClient.send_zb
    #
    # Sends prepared ZB data.
    #
    # zb_data may contain one ZB object or a list of several ZB objects.
    #
    # The client deliberately does not interpret ZB fields. Their contents are
    # application/business data and must already be prepared by the caller.
    # =========================================================================
    def send_zb(self, zb_data):
        if isinstance(zb_data, dict):
            zb_list = [zb_data]

        elif isinstance(zb_data, list):
            zb_list = zb_data

        else:
            self._report_error(
                "Cannot send ZB data: expected dictionary or list"
            )
            return False

        message = {
            "type": "write",
            "data": {
                "zb": zb_list
            }
        }

        return self.send_data(message)

    # =========================================================================
    # ModBusBridgeClient.send_cz
    #
    # Sends prepared CZ data.
    #
    # cz_data may contain one CZ object or a list of several CZ objects.
    # =========================================================================
    def send_cz(self, cz_data):
        if isinstance(cz_data, dict):
            cz_list = [cz_data]

        elif isinstance(cz_data, list):
            cz_list = cz_data

        else:
            self._report_error(
                "Cannot send CZ data: expected dictionary or list"
            )
            return False

        message = {
            "type": "write",
            "data": {
                "cz": cz_list
            }
        }

        return self.send_data(message)

    # =========================================================================
    # ModBusBridgeClient.send_replacement
    #
    # Sends detector replacement information.
    #
    # zb_number:
    #     ZB position number, 1..9.
    #
    # new_sn:
    #     Serial number of the replacement detector.
    # =========================================================================
    def send_replacement(self, zb_number, new_sn):
        try:
            zb_number = int(zb_number)
            new_sn = int(new_sn)

        except (TypeError, ValueError):
            self._report_error(
                "Cannot send replacement: zb_number and new_sn must be integers"
            )
            return False

        if not 1 <= zb_number <= 9:
            self._report_error(
                "Cannot send replacement: ZB number must be in range 1..9"
            )
            return False

        if new_sn <= 0:
            self._report_error(
                "Cannot send replacement: serial number must be positive"
            )
            return False

        message = {
            "type": "write",
            "data": {
                "replacement": {
                    "zb_number": zb_number,
                    "new_sn": new_sn
                }
            }
        }

        return self.send_data(message)

    # =========================================================================
    # ModBusBridgeClient.request_fullness
    #
    # Explicitly asks ModBusBridgeService to read tank fullness.
    #
    # Normally Bridge already performs periodic fullness reading, but keeping
    # this method provides a clean protocol-level operation for diagnostics and
    # future application use.
    # =========================================================================
    def request_fullness(self):
        message = {
            "type": "read"
        }

        return self.send_data(message)

    # =========================================================================
    # ModBusBridgeClient._open_connection
    #
    # Creates and connects a fresh TCP socket.
    #
    # The socket is completely prepared before it becomes the current active
    # socket. This avoids exposing a half-connected socket to send_data().
    # =========================================================================
    def _open_connection(self):
        if self._stop_event.is_set():
            return False

        if self._manual_disconnect:
            return False

        if self.is_connected():
            return True

        new_socket = None

        try:
            self.logMessage.emit(
                f"Connecting to ModBusBridgeService "
                f"{self.host}:{self.port}..."
            )

            new_socket = socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM
            )

            # Prevent connect() from blocking forever.
            new_socket.settimeout(self.connect_timeout)

            new_socket.connect(
                (self.host, self.port)
            )

            # Reader uses a finite timeout so shutdown can be detected.
            new_socket.settimeout(self.receive_timeout)

        except (OSError, socket.error) as exc:
            if new_socket is not None:
                try:
                    new_socket.close()
                except OSError:
                    pass

            self.logMessage.emit(
                f"Connection attempt failed: {exc}"
            )

            return False

        with self._socket_lock:

            # Another thread could theoretically establish connection while
            # this connection attempt was in progress.
            #
            # In that case the newly created redundant socket is closed.
            if self._socket is not None and self.is_connected():
                try:
                    new_socket.close()
                except OSError:
                    pass

                return True

            self._socket = new_socket

        with self._state_lock:
            self._connected = True
            self._disconnected_signal_sent = False

        self._reconnect_event.clear()

        self.logMessage.emit(
            f"Connected to ModBusBridgeService "
            f"{self.host}:{self.port}"
        )

        self.connected.emit()

        self._start_reader_thread(new_socket)

        return True

    # =========================================================================
    # ModBusBridgeClient._start_reader_thread
    #
    # Starts the receive worker for one specific socket instance.
    #
    # Passing the socket directly to the thread is important: an old reader
    # must never accidentally start reading from a newer replacement socket.
    # =========================================================================
    def _start_reader_thread(self, current_socket):
        reader_thread = threading.Thread(
            target=self._read_loop,
            args=(current_socket,),
            name="ModBusBridgeReader",
            daemon=True
        )

        self._reader_thread = reader_thread

        reader_thread.start()

    # =========================================================================
    # ModBusBridgeClient._read_loop
    #
    # Continuously receives TCP data.
    #
    # Incoming data is accumulated as bytes, NOT text.
    #
    # This is important because one UTF-8 character may be split between two
    # recv() calls. Decoding each recv() independently can therefore produce a
    # false UnicodeDecodeError.
    #
    # Only a complete newline-delimited frame is decoded.
    # =========================================================================
    def _read_loop(self, current_socket):
        receive_buffer = bytearray()

        try:
            while not self._stop_event.is_set():

                # Stop an obsolete reader after reconnect.
                with self._socket_lock:
                    if self._socket is not current_socket:
                        break

                try:
                    chunk = current_socket.recv(4096)

                except socket.timeout:
                    # Normal timeout.
                    # It only gives us an opportunity to check stop_event.
                    continue

                except (OSError, socket.error) as exc:
                    if not self._stop_event.is_set():
                        self._handle_connection_failure(
                            f"Receive error: {exc}",
                            failed_socket=current_socket
                        )

                    return

                # recv() == b"" means orderly shutdown by the remote side.
                if not chunk:
                    if not self._stop_event.is_set():
                        self._handle_connection_failure(
                            "ModBusBridgeService closed the connection",
                            failed_socket=current_socket
                        )

                    return

                receive_buffer.extend(chunk)

                # Protect against a connection that continuously sends data
                # without the protocol newline delimiter.
                if (
                    b"\n" not in receive_buffer
                    and len(receive_buffer) > self.max_message_size
                ):
                    self._handle_connection_failure(
                        "Incoming message exceeded maximum allowed size",
                        failed_socket=current_socket
                    )

                    return

                while True:
                    newline_position = receive_buffer.find(b"\n")

                    if newline_position < 0:
                        break

                    frame = bytes(
                        receive_buffer[:newline_position]
                    )

                    del receive_buffer[:newline_position + 1]

                    # Empty lines are harmless and ignored.
                    if not frame.strip():
                        continue

                    if len(frame) > self.max_message_size:
                        self._handle_connection_failure(
                            "Incoming JSON frame exceeded maximum allowed size",
                            failed_socket=current_socket
                        )

                        return

                    self._process_received_frame(frame)

        finally:
            # The reader itself does not blindly close the current socket here.
            # Connection state is changed only through the central failure /
            # disconnect methods.
            pass

    # =========================================================================
    # ModBusBridgeClient._process_received_frame
    #
    # Decodes and validates one complete newline-delimited JSON frame.
    #
    # A malformed JSON frame is reported but does NOT immediately destroy the
    # TCP connection. The next correctly framed message can still be processed.
    # =========================================================================
    def _process_received_frame(self, frame):
        try:
            text = frame.decode("utf-8")

        except UnicodeDecodeError as exc:
            self._report_error(
                f"Invalid UTF-8 received from ModBusBridgeService: {exc}"
            )
            return

        try:
            message = json.loads(text)

        except json.JSONDecodeError as exc:
            self._report_error(
                f"Invalid JSON received from ModBusBridgeService: {exc}"
            )
            return

        if not isinstance(message, dict):
            self._report_error(
                "Invalid message received: top-level JSON value is not an object"
            )
            return

        self.logMessage.emit(
            f"Received JSON message from ModBusBridgeService: {message}"
        )

        self.dataReceived.emit(message)

    # =========================================================================
    # ModBusBridgeClient._handle_connection_failure
    #
    # Central handler for unexpected communication loss.
    #
    # The failed socket is supplied explicitly so an old reader thread cannot
    # accidentally close a newer connection created by reconnect logic.
    # =========================================================================
    def _handle_connection_failure(
        self,
        message,
        failed_socket=None
    ):
        should_process_failure = False

        with self._socket_lock:

            if (
                failed_socket is None
                or self._socket is failed_socket
            ):
                should_process_failure = True

        if not should_process_failure:
            # The error belongs to an obsolete socket.
            return

        self._report_error(message)

        self._close_current_socket(
            emit_disconnected=True,
            reason="Connection to ModBusBridgeService lost",
            expected_socket=failed_socket
        )

        self._request_reconnect()

    # =========================================================================
    # ModBusBridgeClient._close_current_socket
    #
    # Safely detaches and closes the active socket.
    #
    # expected_socket prevents an old worker from closing a new connection.
    # =========================================================================
    def _close_current_socket(
        self,
        emit_disconnected,
        reason,
        expected_socket=None
    ):
        socket_to_close = None

        with self._socket_lock:

            if (
                expected_socket is not None
                and self._socket is not expected_socket
            ):
                return

            socket_to_close = self._socket
            self._socket = None

        was_connected = False
        should_emit_disconnected = False

        with self._state_lock:

            was_connected = self._connected
            self._connected = False

            if (
                emit_disconnected
                and was_connected
                and not self._disconnected_signal_sent
            ):
                self._disconnected_signal_sent = True
                should_emit_disconnected = True

        if socket_to_close is not None:

            try:
                socket_to_close.shutdown(socket.SHUT_RDWR)

            except OSError:
                # Socket may already be disconnected.
                pass

            try:
                socket_to_close.close()

            except OSError:
                pass

        if was_connected:
            self.logMessage.emit(reason)

        if should_emit_disconnected:
            self.disconnected.emit()

    # =========================================================================
    # ModBusBridgeClient._request_reconnect
    #
    # Requests automatic reconnection unless the user/application intentionally
    # disconnected the client.
    # =========================================================================
    def _request_reconnect(self):
        if self._stop_event.is_set():
            return

        if self._manual_disconnect:
            return

        self._ensure_reconnect_thread()
        self._reconnect_event.set()

    # =========================================================================
    # ModBusBridgeClient._ensure_reconnect_thread
    #
    # Creates one persistent reconnect worker.
    #
    # There must never be several reconnect threads racing to create sockets.
    # =========================================================================
    def _ensure_reconnect_thread(self):
        if (
            self._reconnect_thread is not None
            and self._reconnect_thread.is_alive()
        ):
            return

        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            name="ModBusBridgeReconnect",
            daemon=True
        )

        self._reconnect_thread.start()

    # =========================================================================
    # ModBusBridgeClient._reconnect_loop
    #
    # Waits until reconnect is requested and then periodically attempts to
    # restore the connection.
    #
    # The worker is created once and lives until shutdown().
    # =========================================================================
    def _reconnect_loop(self):
        while not self._stop_event.is_set():

            # Wait until connection recovery is actually required.
            self._reconnect_event.wait(timeout=0.5)

            if self._stop_event.is_set():
                break

            if not self._reconnect_event.is_set():
                continue

            if self._manual_disconnect:
                self._reconnect_event.clear()
                continue

            if self.is_connected():
                self._reconnect_event.clear()
                continue

            if self._open_connection():
                self._reconnect_event.clear()
                continue

            # Wait interruptibly so shutdown does not have to wait for the full
            # reconnect interval.
            self._stop_event.wait(
                self.reconnect_interval
            )

    # =========================================================================
    # ModBusBridgeClient._report_error
    #
    # Sends one error both through the dedicated error signal and through the
    # diagnostic log signal.
    # =========================================================================
    def _report_error(self, message):
        self.errorOccurred.emit(message)
        self.logMessage.emit(
            f"ERROR: {message}"
        )