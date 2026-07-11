def break_string_into_array(string, max_length):
  words = string.split()
  result = []
  current_substring = ""

  for word in words:
    if len(current_substring) + len(word) + 1 <= max_length:
      current_substring += word + " "
    else:
      result.append(current_substring.strip())
      current_substring = word + " "

  if current_substring:
    result.append(current_substring.strip())

  return result

string = "This is a long string that needs to be broken into smaller pieces."
max_length = 20
result = break_string_into_array(string, max_length)
print(result)