import numpy as np
from LRFHSS.base.base import *
from LRFHSS.base.LRFHSSTransmission import LRFHSSTransmission
from LRFHSS.base.RadioSignalQuality import RadioSignalQuality
from LRFHSS.base.RadioLinkBudget import RadioLinkBudget

class Processor():
    """
    A class for decoding LoRa transmissions. Processor / Demodulator

    Args:
        granularity (int): The granularity of the decoding process, in slots.
        CR (int): The coding rate of the LoRa transmissions.

    Attributes:
        granularity (int): The granularity of the decoding process, in slots.
        CR (int): The coding rate of the LoRa transmissions.
        _current_tx (LRFHSSTransmission): The current transmission being decoded.
        _fragment_status (list[int]): Status of each fragment of the current frame.
        is_busy (bool): Whether the processor is currently decoding a transmission.
        collided_packets (int): The number of transmissions that have collided.
        decoded_packets (int): The number of transmissions that have been decoded successfully.
        decoded_bytes (int): The number of bytes that have been decoded successfully.

    Methods:
        reset(): Resets all counters and states to initial state.
        get_thershold(seq_length: int) -> int:
            Determine the minimum number of fragments needed to successfully
            decode a packet. Two Coding Rates supported:
                if CR==1 then a 1/3 of fragmenst are required
                if CR==2 then a 2/3 of fragmenst are required
        start_decoding(start_event : StartEvent) -> None:
            Lock processor to the given transmission.
        finish_decoding(end_event : EndEvent) -> None:
            Check if the ending trasnmission handed by the gateway corresponds
            to the one being decoded by this processor then determine the outcome
            of the transmission and update counters 
        handle_collision(collision_event : CollisionEvent) -> None:
            Check if the current transmission being decoded matches the given
            collision event and if so updates the counter of collided fragments
    """

    def __init__(self, CR: int, timeGranularity: int, freqGranularity: int, use_earlydrop: bool,
                 use_earlydecode: bool, use_headerdrop: bool, baseFreq: int, collision_method: str) -> None:
        self.CR = CR
        self.timeGranularity = timeGranularity
        self.freqGranularity = freqGranularity
        self.freqPerSlot = OBW_BW / self.freqGranularity
        self.headerSlots = round(timeGranularity * HDR_TIME / FRG_TIME)
        self.use_earlydrop = use_earlydrop
        self.use_earlydecode = use_earlydecode
        self.use_headerdrop = use_headerdrop
        self.baseFreq = baseFreq
        self.collision_method = collision_method
        self.th2 = TH2
        self.symbolThreshold = SYM_THRESH

        self.tracked_txs = 0
        self.decoded_bytes = 0
        self.header_drop_packets = 0
        self.decoded_hrd_pld = 0  # case 1
        self.decoded_hdr = 0      # case 3
        self.decodable_pld = 0    # case 2
        self.collided_hdr_pld = 0 # case 4
        self.decoded = []
        self.decoded_headers = []


    def reset(self) -> None:
        """
        Reset all counters and states to initial state
        """
        self.tracked_txs = 0
        self.decoded_bytes = 0
        self.header_drop_packets = 0
        self.decoded_hrd_pld = 0  # case 1
        self.decoded_hdr = 0      # case 3
        self.decodable_pld = 0    # case 2
        self.collided_hdr_pld = 0 # case 4
        self.decoded = []
        self.decoded_headers = []


    def get_minfragments(self, seq_length : int) -> int:
        """
        Determine minimum required number of fragment for 
        successful decoding. Two Coding Rates supported:
            if CR==1 then a 1/3 of fragmenst are required
            if CR==2 then a 2/3 of fragmenst are required
        """
        return np.ceil(self.CR * seq_length / 3)
    

    def isCollided(self, args) -> bool:

        if self.collision_method == 'strict':
            return self.isCollided_strict(args)
    
        if self.collision_method == 'SINR':
            return self.isCollided_power(args)
        
        raise Exception(f"Collision determination method ```{self.collision_method}``` unknown") 


    def isCollided_strict(self, args: list) -> bool:
        # the header or fragment is collided if any slot is collided
        return not (args[0] == 1).all()
    

    def isCollided_power(self, args: list) -> bool:
        signal_power_mw = args[0]
        interferenceBlock = args[1]
        isHdr = args[2]
        noise_power = RadioSignalQuality.noise_power_mw()

        collidedslots = 0
        timeslots = self.headerSlots if isHdr else self.timeGranularity

        for t in range(timeslots):
            SINRt_dB = RadioSignalQuality.sinr_db(
                signal_power_mw=signal_power_mw,
                interference_power_mw=interferenceBlock[t],
                noise_power_mw=noise_power,
            )

            if SINRt_dB < self.th2:
                # Keep your existing header/fragments behavior
                if t == 0:
                    return True
                collidedslots += 1

        return (collidedslots / timeslots) > self.symbolThreshold

    def received_signal_power_mw(self, tx: LRFHSSTransmission) -> float:
        distance_m = float(getattr(tx, "distance_m", getattr(tx, "distance", SAT_H)))
        tx_power_dbm = float(getattr(tx, "power", TX_PWR_DB))
        return float(
            RadioLinkBudget.received_power_mw(
                tx_power_dbm=tx_power_dbm,
                distance_m=distance_m,
                carrier_hz=OCW_FC,
            )
        )
    

    def predecode_headers(self, tx: LRFHSSTransmission, rcvM: np.ndarray, dynamic: bool) -> int:

        collided_headers = 0
        dopplershift = round(tx.dopplerShift[0] / self.freqPerSlot)

        if self.collision_method == 'SINR':
            estSignalPower, headersPi, fragmentsPi = self.get_power_estimations(tx, rcvM, dynamic)

        time = tx.startSlot
        for fh, obw in enumerate(tx.sequence):

            # variable doppler shift per header / fragment
            if dynamic:
                dopplershift = round(tx.dopplerShift[fh] / self.freqPerSlot)

            startFreq = self.baseFreq + obw * self.freqGranularity + dopplershift
            endFreq = startFreq + self.freqGranularity

            # header
            if fh < tx.numHeaders:

                endTime = time + self.headerSlots

                if self.collision_method == 'strict':
                    args = [rcvM[tx.ocw, startFreq : endFreq, time : endTime]]
                if self.collision_method == 'SINR':
                    args = [estSignalPower, headersPi[fh], True]

                if self.isCollided(args):
                    collided_headers += 1
                
                time = endTime

            else: break

        if collided_headers < tx.numHeaders:
            self.decoded_headers.append(tx)
        
        return endTime


    def decode(self, tx: LRFHSSTransmission, rcvM: np.ndarray, dynamic: bool) -> int:
        """
        Determine status of incoming transmissions and return free up time
        """

        self.tracked_txs += 1
        collided_headers = 0
        decoded_fragments = 0
        collided_fragments = 0

        dopplershift = round(tx.dopplerShift[0] / self.freqPerSlot)
        maxFrgCollisions = tx.numFragments - self.get_minfragments(tx.numFragments)

        if self.collision_method == 'SINR':
            estSignalPower, headersPi, fragmentsPi = self.get_power_estimations(tx, rcvM, dynamic)

        time = tx.startSlot
        for fh, obw in enumerate(tx.sequence):

            # variable doppler shift per header / fragment
            if dynamic:
                dopplershift = round(tx.dopplerShift[fh] / self.freqPerSlot)

            startFreq = self.baseFreq + obw * self.freqGranularity + dopplershift
            endFreq = startFreq + self.freqGranularity

            # header
            if fh < tx.numHeaders:

                endTime = time + self.headerSlots

                if self.collision_method == 'strict':
                    args = [rcvM[tx.ocw, startFreq : endFreq, time : endTime]]
                if self.collision_method == 'SINR':
                    args = [estSignalPower, headersPi[fh], True]

                if self.isCollided(args):
                    collided_headers += 1
                
                time = endTime

            # fragment
            else:

                # collided header, abort payload reception
                if self.use_headerdrop and collided_headers == tx.numHeaders:
                    self.header_drop_packets += 1
                    return endTime

                endTime = time + self.timeGranularity

                if self.collision_method == 'strict':
                    args = [rcvM[tx.ocw, startFreq : endFreq, time : endTime]]
                if self.collision_method == 'SINR':
                    args = [estSignalPower, fragmentsPi[fh-tx.numHeaders], False]

                if self.isCollided(args):
                    collided_fragments += 1
                else:
                    decoded_fragments += 1

                # early decode - decoded or decodable payload
                if self.use_earlydecode and decoded_fragments >= self.get_minfragments(tx.numFragments):

                    # case 1
                    if collided_headers < tx.numHeaders:
                        self.decoded_hrd_pld += 1
                        self.decoded_bytes += tx.payload_size
                        self.decoded.append([tx, 1])

                    # case 2
                    else:
                        self.decodable_pld += 1

                    return endTime

                # early drop - collided payload
                if self.use_earlydrop and collided_fragments > maxFrgCollisions:
                    
                    # case 3
                    if collided_headers < tx.numHeaders:
                        self.decoded_hdr += 1
                        self.decoded.append([tx, 0])

                    # case 4
                    else:
                        self.collided_hdr_pld += 1
                    
                    return endTime

                time = endTime
        

    def get_power_estimations(self, tx: LRFHSSTransmission, rcvM: np.ndarray, dynamic: bool) -> bool:

        dopplershift = round(tx.dopplerShift[0] / self.freqPerSlot)

        headers = np.zeros((tx.numHeaders, self.freqGranularity, self.headerSlots))
        fragments = np.zeros((tx.numFragments, self.freqGranularity, self.timeGranularity))

        time = tx.startSlot
        for fh, obw in enumerate(tx.sequence):

            # variable doppler shift per header / fragment
            if dynamic:
                dopplershift = round(tx.dopplerShift[fh] / self.freqPerSlot)

            startFreq = self.baseFreq + obw * self.freqGranularity + dopplershift
            endFreq = startFreq + self.freqGranularity

            # header
            if fh < tx.numHeaders:
                endTime = time + self.headerSlots
                headers[fh] = rcvM[tx.ocw, startFreq : endFreq, time : endTime]

            # fragment
            else:
                endTime = time + self.timeGranularity
                fragments[fh-tx.numHeaders] = rcvM[tx.ocw, startFreq : endFreq, time : endTime]
            
            time = endTime
        _, headersPi, fragmentsPi = RadioSignalQuality.estimate_signal_and_interference(headers, fragments)
        estSignalPower = self.received_signal_power_mw(tx)
        return estSignalPower, headersPi, fragmentsPi
    
