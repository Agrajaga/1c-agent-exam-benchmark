"""Kill-on-close Job Object, assigned before any child code runs."""
import ctypes
from ctypes import wintypes as w

k = ctypes.WinDLL('kernel32', use_last_error=True)
n = ctypes.WinDLL('ntdll')


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                ('active_limit', w.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IO(ctypes.Structure):
    _fields_ = [(x, ctypes.c_uint64) for x in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class Limits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IO), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class Accounting(ctypes.Structure):
    _fields_ = [(x, ctypes.c_int64) for x in ('user', 'kernel', 'period_user', 'period_kernel')] + [
        (x, w.DWORD) for x in ('faults', 'total', 'active', 'terminated')]


for name, args, result in (
    ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
    ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
    ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
    ('QueryInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
    ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
    ('CloseHandle', [w.HANDLE], w.BOOL),
):
    fn = getattr(k, name); fn.argtypes = args; fn.restype = result
n.NtResumeProcess.argtypes = [w.HANDLE]; n.NtResumeProcess.restype = ctypes.c_long


def checked(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


class Job:
    def __init__(self, process):
        self.handle = checked(k.CreateJobObjectW(None, None))
        try:
            limits = Limits(); limits.basic.flags = 0x2000
            checked(k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            checked(k.AssignProcessToJobObject(self.handle, int(process._handle)))
            if n.NtResumeProcess(int(process._handle)) != 0:
                raise OSError('Cannot resume supervised process')
        except BaseException:
            self.close()
            raise

    def active(self):
        info = Accounting()
        checked(k.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None))
        return info.active > 0

    def terminate(self):
        checked(k.TerminateJobObject(self.handle, 1))

    def close(self):
        if self.handle:
            k.CloseHandle(self.handle); self.handle = None
