from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemodSnapshot:
    tick: int
    idle: int
    booked: int
    busy: int
    sleep: int
    total: int

    @property
    def engaged(self) -> int:
        return int(self.booked + self.busy)


@dataclass(frozen=True)
class _Reservation:
    payload_start_tick: int
    payload_end_tick: int


class RecursiveReuseDemodAllocator:
    """
    Paper-inspired demodulator scheduler with recursive reuse.

    This approximates the FIFO-RR1/FIFO-RR2 flow from:
    "Improving LoRa Scalability by a Recursive Reuse of Demodulators"
    (GLOBECOM 2020), while preserving a power-state layer (idle/sleep).

    Service states:
    - IDLE: no reservation
    - BOOKED: reserved for a future payload
    - BUSY: currently demodulating payload
    """

    __slots__ = (
        "_num_demods",
        "_idle_to_sleep_ticks",
        "_default_payload_ticks",
        "_tick",
        "_schedules",
        "_sleeping",
        "_idle_streak",
    )

    def __init__(
        self,
        num_demods: int,
        idle_to_sleep_ticks: int = 2,
        default_payload_ticks: int = 1,
    ) -> None:
        self._num_demods = max(0, int(num_demods))
        self._idle_to_sleep_ticks = max(0, int(idle_to_sleep_ticks))
        self._default_payload_ticks = max(1, int(default_payload_ticks))
        self._tick = 0
        self._schedules: list[list[_Reservation]] = [[] for _ in range(self._num_demods)]
        self._sleeping: list[bool] = [False] * self._num_demods
        self._idle_streak: list[int] = [0] * self._num_demods

    @property
    def total_demods(self) -> int:
        return int(self._num_demods)

    def advance_tick(self, ticks: int = 1) -> DemodSnapshot:
        steps = max(1, int(ticks))
        for _ in range(steps):
            self._tick += 1
            for i in range(self._num_demods):
                self._drop_finished(i)
                if self._schedules[i]:
                    self._sleeping[i] = False
                    self._idle_streak[i] = 0
                    continue
                if self._sleeping[i]:
                    continue
                self._idle_streak[i] += 1
                if self._idle_streak[i] > self._idle_to_sleep_ticks:
                    self._sleeping[i] = True
                    self._idle_streak[i] = 0
        return self.snapshot()

    def snapshot(self) -> DemodSnapshot:
        idle = 0
        booked = 0
        busy = 0
        sleep = 0
        for i in range(self._num_demods):
            state = self._service_state(i)
            if self._sleeping[i] and state == "IDLE":
                sleep += 1
            elif state == "IDLE":
                idle += 1
            elif state == "BOOKED":
                booked += 1
            else:
                busy += 1
        return DemodSnapshot(
            tick=int(self._tick),
            idle=int(idle),
            booked=int(booked),
            busy=int(busy),
            sleep=int(sleep),
            total=int(self._num_demods),
        )

    def allocate(
        self,
        requested_frames: int,
        preamble_ticks: int = 1,
        payload_ticks: int | None = None,
        max_frame_ticks: int | None = None,
    ) -> DemodSnapshot:
        req = max(0, int(requested_frames))
        if req <= 0 or self._num_demods <= 0:
            return self.snapshot()

        preamble = max(1, int(preamble_ticks))
        payload = max(1, int(self._default_payload_ticks if payload_ticks is None else payload_ticks))
        frame_ticks = max(preamble + payload, int(max_frame_ticks) if max_frame_ticks is not None else preamble + payload)

        for _ in range(req):
            accepted = self._try_fifo_rr1(
                preamble_ticks=preamble,
                payload_ticks=payload,
                max_frame_ticks=frame_ticks,
            )
            if not accepted:
                self._try_fifo_rr2(
                    preamble_ticks=preamble,
                    payload_ticks=payload,
                    max_frame_ticks=frame_ticks,
                )
        return self.snapshot()

    def _drop_finished(self, demod_index: int) -> None:
        sch = self._schedules[demod_index]
        while sch and sch[0].payload_end_tick <= self._tick:
            sch.pop(0)

    def _service_state(self, demod_index: int) -> str:
        sch = self._schedules[demod_index]
        if not sch:
            return "IDLE"
        first = sch[0]
        if first.payload_start_tick <= self._tick < first.payload_end_tick:
            return "BUSY"
        return "BOOKED"

    def _next_start_tick(self, demod_index: int) -> int | None:
        sch = self._schedules[demod_index]
        if not sch:
            return None
        return int(sch[0].payload_start_tick)

    def _wake_one_sleeping(self) -> int | None:
        for i in range(self._num_demods):
            if self._sleeping[i] and not self._schedules[i]:
                self._sleeping[i] = False
                self._idle_streak[i] = 0
                return i
        return None

    def _reserve_front(self, demod_index: int, payload_start: int, payload_end: int) -> None:
        self._schedules[demod_index].insert(
            0,
            _Reservation(payload_start_tick=int(payload_start), payload_end_tick=int(payload_end)),
        )
        self._sleeping[demod_index] = False
        self._idle_streak[demod_index] = 0

    def _reserve_back(self, demod_index: int, payload_start: int, payload_end: int) -> None:
        self._schedules[demod_index].append(
            _Reservation(payload_start_tick=int(payload_start), payload_end_tick=int(payload_end)),
        )
        self._sleeping[demod_index] = False
        self._idle_streak[demod_index] = 0

    def _find_rr1_candidate(self, max_deadline_tick: int) -> int | None:
        for i in range(self._num_demods):
            if self._sleeping[i]:
                continue
            state = self._service_state(i)
            if state == "IDLE":
                return i
            if state == "BOOKED":
                next_tick = self._next_start_tick(i)
                if next_tick is not None and next_tick > max_deadline_tick:
                    return i
        return None

    def _try_fifo_rr1(
        self,
        preamble_ticks: int,
        payload_ticks: int,
        max_frame_ticks: int,
    ) -> bool:
        payload_start = self._tick + preamble_ticks
        payload_end = payload_start + payload_ticks
        max_deadline = self._tick + max_frame_ticks

        demod_index = self._find_rr1_candidate(max_deadline_tick=max_deadline)
        if demod_index is None:
            demod_index = self._wake_one_sleeping()
            if demod_index is not None:
                state = self._service_state(demod_index)
                if state != "IDLE":
                    demod_index = None
        if demod_index is None:
            return False

        self._reserve_front(demod_index, payload_start=payload_start, payload_end=payload_end)
        return True

    def _try_fifo_rr2(
        self,
        preamble_ticks: int,
        payload_ticks: int,
        max_frame_ticks: int,
    ) -> bool:
        _ = max_frame_ticks
        new_payload_start = self._tick + preamble_ticks
        new_payload_end = new_payload_start + payload_ticks
        for i in range(self._num_demods):
            if self._sleeping[i]:
                continue
            if self._service_state(i) != "BUSY":
                continue
            sch = self._schedules[i]
            if len(sch) != 1:
                continue
            busy_end = int(sch[0].payload_end_tick)
            if busy_end <= new_payload_start:
                self._reserve_back(i, payload_start=new_payload_start, payload_end=new_payload_end)
                return True
        return False
