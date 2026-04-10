import React, { useState } from 'react';
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  isToday,
  parseISO,
  startOfMonth,
  startOfWeek,
  subMonths,
  subDays,
  startOfWeek as startOfWeekUtil,
  endOfWeek as endOfWeekUtil,
  startOfYear,
  endOfYear,
} from 'date-fns';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';

interface DateRangePickerCalendarProps {
  startDate: string;
  endDate: string;
  onStartDateChange: (date: string) => void;
  onEndDateChange: (date: string) => void;
}

export const DateRangePickerCalendar: React.FC<DateRangePickerCalendarProps> = ({
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selectionMode, setSelectionMode] = useState<'start' | 'end'>('start');

  const parseDateString = (value: string) => parseISO(value);

  const start = startDate ? parseDateString(startDate) : null;
  const end = endDate ? parseDateString(endDate) : null;

  const monthStart = startOfMonth(currentMonth);
  const monthEnd = endOfMonth(currentMonth);
  const gridStart = startOfWeek(monthStart);
  const gridEnd = endOfWeek(monthEnd);
  const days = eachDayOfInterval({ start: gridStart, end: gridEnd });

  const handleToggleOpen = () => {
    if (!isOpen) {
      if (start) {
        setCurrentMonth(start);
      }
      setSelectionMode(startDate && !endDate ? 'end' : 'start');
    }
    setIsOpen((previous) => !previous);
  };

  const handleDayClick = (day: Date) => {
    const dateStr = format(day, 'yyyy-MM-dd');

    if (selectionMode === 'start') {
      onStartDateChange(dateStr);
      onEndDateChange('');
      setSelectionMode('end');
    } else {
      const selectedDate = parseDateString(dateStr);
      if (start && selectedDate < start) {
        onStartDateChange(dateStr);
        onEndDateChange(format(start, 'yyyy-MM-dd'));
      } else {
        onEndDateChange(dateStr);
      }
      setSelectionMode('start');
      setIsOpen(false);
    }
  };

  const handleQuickSelect = (getRange: () => [Date, Date]) => {
    const [s, e] = getRange();
    onStartDateChange(format(s, 'yyyy-MM-dd'));
    onEndDateChange(format(e, 'yyyy-MM-dd'));
    setSelectionMode('start');
    setIsOpen(false);
  };

  const handleClearDates = () => {
    onStartDateChange('');
    onEndDateChange('');
    setSelectionMode('start');
  };

  const isInRange = (day: Date): boolean => {
    if (!start || !end) return false;
    return day >= start && day <= end;
  };

  const isStartDay = (day: Date): boolean => {
    return start ? isSameDay(day, start) : false;
  };

  const isEndDay = (day: Date): boolean => {
    return end ? isSameDay(day, end) : false;
  };

  const displayText = () => {
    if (!startDate && !endDate) return 'Select date range...';
    if (startDate && !endDate) return `From ${format(parseDateString(startDate), 'MMM dd')}`;
    if (startDate && endDate) {
      const parsedStart = parseDateString(startDate);
      const parsedEnd = parseDateString(endDate);
      const sameMonth = isSameMonth(parsedStart, parsedEnd);
      if (sameMonth) {
        return `${format(parsedStart, 'MMM dd')} - ${format(parsedEnd, 'dd, yyyy')}`;
      }
      return `${format(parsedStart, 'MMM dd')} - ${format(parsedEnd, 'MMM dd, yyyy')}`;
    }
    return 'Select date range...';
  };

  return (
    <div className="relative">
      <button
        onClick={handleToggleOpen}
        className="w-full px-3 py-2 border rounded bg-white text-left flex items-center justify-between hover:bg-muted"
      >
        <span>{displayText()}</span>
        <span className="text-muted-foreground text-xs">
          {isOpen ? '▼' : '◀'}
        </span>
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute z-50 top-full mt-2 left-0 bg-card border rounded-lg shadow-lg p-4 min-w-max">
            <div className="space-y-4">
              {/* Quick Select Buttons */}
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => handleQuickSelect(() => {
                    const today = new Date();
                    return [today, today];
                  })}
                  className="text-xs px-2 py-1.5 border rounded hover:bg-muted transition"
                >
                  Today
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickSelect(() => {
                    const now = new Date();
                    return [startOfWeekUtil(now), endOfWeekUtil(now)];
                  })}
                  className="text-xs px-2 py-1.5 border rounded hover:bg-muted transition"
                >
                  This Week
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickSelect(() => {
                    const now = new Date();
                    return [subDays(now, 7), now];
                  })}
                  className="text-xs px-2 py-1.5 border rounded hover:bg-muted transition"
                >
                  Last 7 Days
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickSelect(() => {
                    const now = new Date();
                    return [startOfMonth(now), endOfMonth(now)];
                  })}
                  className="text-xs px-2 py-1.5 border rounded hover:bg-muted transition"
                >
                  This Month
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickSelect(() => {
                    const now = new Date();
                    return [startOfYear(now), endOfYear(now)];
                  })}
                  className="text-xs px-2 py-1.5 border rounded hover:bg-muted transition"
                >
                  This Year
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickSelect(() => {
                    const now = new Date();
                    return [subDays(now, 90), now];
                  })}
                  className="text-xs px-2 py-1.5 border rounded hover:bg-muted transition"
                >
                  Last 90 Days
                </button>
              </div>

              {/* Calendar Header */}
              <div className="border-t pt-4">
                <div className="flex items-center justify-between mb-4">
                  <button
                    type="button"
                    onClick={() => setCurrentMonth(subMonths(currentMonth, 1))}
                    className="p-1 hover:bg-muted rounded"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <h3 className="text-sm font-semibold min-w-[120px] text-center">
                    {format(currentMonth, 'MMMM yyyy')}
                  </h3>
                  <button
                    type="button"
                    onClick={() => setCurrentMonth(addMonths(currentMonth, 1))}
                    className="p-1 hover:bg-muted rounded"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>

                {/* Weekday Headers */}
                <div className="grid grid-cols-7 gap-1 mb-2">
                  {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => (
                    <div key={day} className="text-center text-xs font-medium text-muted-foreground w-8">
                      {day}
                    </div>
                  ))}
                </div>

                {/* Calendar Days */}
                <div className="grid grid-cols-7 gap-1">
                  {days.map((day) => {
                    const inRange = isInRange(day);
                    const isStart = isStartDay(day);
                    const isEnd = isEndDay(day);
                    const isFromThisMonth = isSameMonth(day, currentMonth);
                    const isTodayFlag = isToday(day);

                    return (
                      <button
                        key={day.toString()}
                        type="button"
                        onClick={() => handleDayClick(day)}
                        className={`
                          w-8 h-8 text-xs rounded transition
                          ${!isFromThisMonth && 'text-muted-foreground/50'}
                          ${isStart && 'bg-primary text-primary-foreground font-bold'}
                          ${isEnd && 'bg-primary text-primary-foreground font-bold'}
                          ${inRange && !isStart && !isEnd && 'bg-primary/20'}
                          ${isTodayFlag && !isStart && !isEnd && 'border border-primary'}
                          ${!inRange && !isStart && !isEnd && isFromThisMonth && 'hover:bg-muted'}
                          ${!inRange && !isStart && !isEnd && !isFromThisMonth && 'cursor-default'}
                        `}
                        disabled={!isFromThisMonth}
                      >
                        {format(day, 'd')}
                      </button>
                    );
                  })}
                </div>

                {/* Selection Mode Indicator */}
                <div className="mt-4 text-xs text-muted-foreground text-center">
                  {selectionMode === 'start' ? 'Select start date' : 'Select end date'}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2 border-t pt-4">
                {(startDate || endDate) && (
                  <button
                    type="button"
                    onClick={handleClearDates}
                    className="flex-1 text-xs px-2 py-1.5 border rounded hover:bg-destructive/10 text-destructive transition flex items-center justify-center gap-1"
                  >
                    <X className="w-3 h-3" />
                    Clear
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="flex-1 text-xs px-2 py-1.5 bg-primary text-primary-foreground rounded hover:bg-primary/90 transition"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
